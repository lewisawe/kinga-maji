# Implementation Plan — Autonomous Watcher + 2024 El Niño Flood Replay

Two ADDITIVE improvements to the already-live **Kinga Maji** app. Nothing existing may break: the live site, the pixel-only engine contract, the current API routes/payloads, the fragmented preview-guard sentinel, and the Leaflet 1.9.4 SRI hash all stay intact.

Project root: `/home/sierra/Desktop/projects/builderCenter/zero-to-shipped/kinga-maji`

---

## 0. Context the implementer must know before touching anything

- **Engine is LOCKED.** `engine/depth_engine.py` is reused as-is. The deploy script vendors it to `lambda/depth_engine.py` (a `cp`), so the handler imports `compute_depth`, `fuse_rainfall`, `DepthInput`, `REFERENCE_HEIGHTS_M`, `CATEGORIES` by their exact names. The escalation rule is `fuse_rainfall(depth_result, rainfall_mm_next_24h)`: escalates one category when `rainfall_mm_next_24h >= 20.0 AND depth.depth_m >= 0.10`. Do NOT re-implement this math anywhere server-side; call `fuse_rainfall`.
- **Table key:** DynamoDB `ReportsTable` has partition_key `settlement` (STRING), sort_key `timestamp` (STRING). Alerts share this one table. There is no GSI.
- **HTTP API payload v2.0:** route on `event['requestContext']['http']['method']` and `event['rawPath']`. `_resp()` sets open CORS on every reply.
- **SETTLEMENTS** in the handler: `Mathare (-1.2595, 36.8580)`, `Mukuru (-1.3167, 36.8667)`.
- **Preview-guard sentinel (DESIGN.md "Known fix"):** every page keeps exactly ONE plain `const API = '__API_URL__';` assignment line (deploy injects the real URL into it) AND a fragmented sentinel `const API_PLACEHOLDER = '__API' + '_URL__';`. Guards compare `if (!API || API === API_PLACEHOLDER)`. NEVER write a contiguous `__API_URL__` token inside a guard comparison. After deploy there must be **0 literal `__API_URL__`** anywhere in the uploaded HTML.
- **Leaflet SRI (DESIGN.md "Known fix"):** `app.html` pins leaflet@1.9.4 with JS integrity `sha256-20nQCchB9co0qIjJZRGuk2/Z9VM+kNiyxNV1lvTlZBo=` and CSS integrity `sha256-p4NxAoJBhIIN+hmNHrzRCf9tD/miZyoHS5obTRR9BMY=`. Do not alter these. `replay.html` does NOT need Leaflet (no map) — do not add it.
- **No SNS subscriptions, no external sends.** The watcher only writes ALERT items to DynamoDB. SNS stays untouched (the existing best-effort `_publish` on `/analyze` is unchanged; do NOT add a subscription).

---

## WHAT MUST STAY BYTE-IDENTICAL (verify at the end)

1. Response **shape** of `GET /reports` — `{"reports": [...]}` with the same per-item fields, and SAMPLE_REPORTS fallback unchanged. (The item LIST changes only in that alert items must NOT appear here — see §1.3.)
2. Response shape of `POST /analyze`, `POST /seed`, `GET /health` — unchanged keys and values.
3. `engine/depth_engine.py` — not edited at all.
4. The fragmented sentinel pattern and the single `const API = '__API_URL__';` line per page (and the real-URL re-injection behavior).
5. Leaflet 1.9.4 JS + CSS SRI hashes in `app.html`.
6. SETTLEMENTS coords, the pixel-only VISION_PROMPT, DEMO_COORDS, `_resp` CORS.

---

## 1. Alert item schema + discriminator (DECIDE ONCE, used everywhere)

**Chosen schema.** Alerts live in the SAME `ReportsTable`. To keep the key (settlement+timestamp) collision-free with reports and to let scans cleanly separate the two, every alert item gets:

- `settlement` (PK): the settlement name, same values as reports.
- `timestamp` (SK): ISO-8601 UTC. **Prefixed with `ALERT#`** so an alert's sort key can never collide with a report's plain-ISO timestamp sharing the same settlement+instant. Example: `"ALERT#2024-04-24T06:00:00+00:00"`.
- `item_type`: the explicit discriminator string **`"alert"`**. (Report items do NOT have this field; absence == report.)
- `rainfall_mm` (number): the real Open-Meteo forecast total used.
- `depth_m` (number): the standing-water depth used (latest known report depth for that settlement, or the conservative baseline — see §2).
- `category_key` (string): engine category of the fused result.
- `final_label` (string): `fuse_rainfall(...).final_label`.
- `escalated` (bool): `fuse_rainfall(...).escalated`.
- `message` (string): the exact human-readable WARNING MESSAGE BODY that would be sent over SMS/WhatsApp in production (see §2 for the exact template).
- `trace` (list[str]): `depth-side note(s)` + `fuse_rainfall(...).trace`, so the alert is checkable.
- `lat`, `lon` (numbers): the settlement coords (for parity with report items / future map use).

**Why both a prefixed SK and an `item_type` field:** the `ALERT#` SK prefix guarantees no key collision with any report row; the `item_type == "alert"` field is the explicit, self-documenting filter used by every reader. Readers filter on `item_type`, not on string-prefix guessing.

**How `/reports` stays unaffected (CRITICAL — this is the one place existing payload could regress):** `_reports()` currently does `_table().scan(Limit=50)` and returns every item. After alerts share the table, `_reports()` MUST drop any item where `item_type == "alert"`. Change `_reports()` to filter: keep only items whose `.get("item_type")` is not `"alert"`. Keep `Limit`/sort/SAMPLE_REPORTS-fallback behavior identical otherwise. Verify `/reports` never shows an alert.

**How `/alerts` filters IN:** scan the table, keep only items with `item_type == "alert"`, sort by `timestamp` descending (string sort works — all alert SKs share the `ALERT#` prefix + ISO), return `{"alerts": [...]}`.

---

## 2. New handler logic — `lambda/handler.py` (ADDITIVE only)

All edits are additions or the one `_reports()` filter from §1.3. Do not change existing route handlers' payloads.

### 2.1 Constants (near SETTLEMENTS / after SAMPLE_REPORTS)
- `BASELINE_DEPTH_M = 0.12` — conservative standing-water depth used when a settlement has no prior report. Chosen so it is `>= 0.10` (eligible for escalation under the locked rule) but still in the low "ankle" band, i.e. honest and not alarmist. Document inline that this is a conservative placeholder, not a measurement.
- `DANGER_KEYS = {"dangerous", "evacuate"}` — categories that are "danger threshold crossed" independent of escalation.
- `ALERT_PREFIX = "ALERT#"`.

### 2.2 Helper: latest known depth per settlement
Add `def _latest_depth(settlement: str) -> tuple[float, str]:` that queries the table for that settlement's REPORT items (not alerts), returns `(depth_m, source_note)`:
- Use `_table().query(KeyConditionExpression=Key('settlement').eq(settlement))` (import `from boto3.dynamodb.conditions import Key` lazily inside the function to keep import-without-creds working), or fall back to a `scan` filtered by settlement if query import is a problem.
- From the returned items drop any `item_type == "alert"`; pick the newest by `timestamp`; return `(float(its depth_m), f"latest report {timestamp}")`.
- If none, return `(BASELINE_DEPTH_M, "no prior report; conservative baseline")`.
- Must never raise: wrap in try/except and fall back to `(BASELINE_DEPTH_M, "lookup failed; conservative baseline")`.

### 2.3 Helper: build the exact SMS/WhatsApp message body
Add `def _alert_message(settlement, final_label, advice, depth_m, rainfall_mm) -> str:` returning the EXACT production body, e.g.:
```
KINGA MAJI FLOOD ALERT — {settlement}. {final_label}. Standing water ~{depth_m:.2f} m, forecast rain next 24h {rainfall_mm:.1f} mm. {advice} This is an automated warning; it does not replace official emergency services.
```
This string is stored verbatim in the alert item's `message`. It is the body that would go to SMS/WhatsApp in production; no send happens.

### 2.4 Watcher cycle (the agent)
Add `def _watch_cycle() -> list[dict]:` that, for EACH settlement in `SETTLEMENTS`:
1. `rainfall_mm, rain_ok = rainfall(lat, lon)` — reuse the EXISTING `rainfall()` (real Open-Meteo forecast, no key). Add a trace note if `not rain_ok`.
2. `depth_m, depth_note = _latest_depth(settlement)`.
3. Build a `DepthResult` to feed `fuse_rainfall`. **Do not fabricate pixels** — construct a minimal `DepthResult` directly from the known depth so the locked `fuse_rainfall` can run: categorize `depth_m` via the engine's `CATEGORIES` (reuse the engine's own thresholds — import `CATEGORIES` and pick the category whose `[min_m, max_m)` contains `depth_m`), and populate a `DepthResult(depth_m=depth_m, reference_object="(standing-water baseline)", reference_height_m=0.0, submerged_fraction=0.0, category_key=cat.key, category_label=cat.label, consequence=cat.consequence, trace=[depth_note], ok=True)`. Then call `risk = fuse_rainfall(that_result, rainfall_mm)`.
   - Rationale: `fuse_rainfall` only reads `depth.depth_m`, `depth.category_key`, `depth.category_label`, `depth.consequence` — so a directly-built `DepthResult` is faithful and avoids inventing pixel coordinates. Confirm against the engine source before coding.
4. Decide dispatch: `should_dispatch = risk.escalated OR (risk-final category_key in DANGER_KEYS)`. Determine the fused category_key: if escalated, recompute via the same `CATEGORIES` index-advance the engine uses, OR read it off the engine — simplest: re-categorize using the final label is unreliable, so compute the fused key the same way the engine does (escalated => next category after the base key; else base key). Keep this deterministic and traced.
5. If `should_dispatch`, build the alert item per §1 schema (SK = `ALERT_PREFIX + iso_now`, `item_type="alert"`, `message=_alert_message(...)`, `trace = result.trace + risk.trace`) and `_persist(item)` (reuse existing `_persist`, which Decimal-encodes floats). Collect dispatched items.
6. Return the list of dispatched alert dicts (for the POST /watch response).

### 2.5 New routes `_alerts()` and `_watch()`
- `def _alerts() -> dict:` scan table, keep `item_type == "alert"`, sort by `timestamp` desc, return `_resp(200, {"alerts": items})`. On scan failure, return `_resp(200, {"alerts": []})` (graceful, same spirit as `_reports`). Same open-CORS, no-auth style.
- `def _watch() -> dict:` run `dispatched = _watch_cycle()`; return `_resp(200, {"ok": True, "dispatched": len(dispatched), "alerts": dispatched})`.

### 2.6 Wire routes in `handler()` (ADD two branches; do not reorder existing)
Add, alongside the existing route checks:
```
if path == "/alerts" and method == "GET":
    return _alerts()
if path == "/watch" and method == "POST":
    return _watch()
```
Leave `/health`, `/analyze`, `/reports`, `/seed`, and the 404 fallback exactly as they are.

### 2.7 `_reports()` filter (the only edit to an existing handler)
In `_reports()`, after obtaining `items` from the scan, add `items = [it for it in items if it.get("item_type") != "alert"]` BEFORE the empty-check and sort. This keeps `/reports` byte-identical in shape and content for the judge (reports only), while alerts coexist in the table.

**Verify (local, no AWS):** `cd lambda && python3 -c "import handler"` imports clean (lazy boto3). Then a tiny offline check that `_watch_cycle`'s DepthResult construction + `fuse_rainfall` runs without network by monkeypatching `handler.rainfall` to return `(25.0, True)` and `handler._latest_depth` to return `(0.12, "test")`, asserting a dict with `item_type == "alert"` and a non-empty `message` is produced. Remove the throwaway check after.

---

## 3. CDK — `cdk/kinga_stack.py` (ADDITIVE: 2 routes + EventBridge schedule)

The watcher is a **path inside the existing `handler.handler`** (routes `/alerts`, `/watch`), so no new Lambda code bundle is needed. The EventBridge rule invokes the SAME function on the `/watch` path by sending a synthetic event.

### 3.1 Add the two HTTP routes
In the `routes` list add:
```
("/alerts", apigwv2.HttpMethod.GET),
("/watch", apigwv2.HttpMethod.POST),
```
They attach to the same `integration` in the existing loop. No other API change. DynamoDB RW is already granted (`table.grant_read_write_data(fn)`) — alerts reuse it; no new grant needed.

### 3.2 EventBridge scheduled rule (rate(1 hour))
Add `aws_events as events` and `aws_events_targets as targets` to the imports. After the Lambda + API are defined, add:
```
schedule_rule = events.Rule(
    self, "WatcherSchedule",
    schedule=events.Schedule.rate(Duration.hours(1)),
)
schedule_rule.add_target(targets.LambdaFunction(
    fn,
    event=events.RuleTargetInput.from_object({
        "rawPath": "/watch",
        "requestContext": {"http": {"method": "POST"}},
    }),
))
```
`add_target(LambdaFunction(...))` creates the `lambda:InvokeFunction` permission automatically — do not add a manual permission. The synthetic event matches the handler's routing (`rawPath` + `requestContext.http.method`), so the scheduled invoke hits `_watch()`.

### 3.3 Keep everything else pinned/untouched
`env` stays `account="888577033943", region="us-east-1"` (set in `cdk/app.py`, unchanged). PYTHON_3_13, `Code.from_asset(LAMBDA_ASSET)`, SNS topic, S3/CloudFront, outputs — all unchanged. Purely additive.

**Verify:** `cd cdk && . .venv/bin/activate && cdk synth KingaMajiStack` succeeds and the synth template contains an `AWS::Events::Rule` and the two new API routes. (If `.venv` deps missing, `pip install -r requirements.txt` first.)

---

## 4. Deploy-time seed of ONE real alert — `scripts/deploy.sh`

Goal: `/alerts` is non-empty for a judge immediately after deploy, using a REAL cycle (real Open-Meteo), not a fabricated row.

### 4.1 Trigger one real watcher cycle after seeding reports
Add a new sub-step right after the existing step [6/9] `/seed` call:
```
echo "==> [6b] Seeding one real autonomous alert (POST /watch)"
curl -s -X POST "$API_URL/watch" -H 'content-type: application/json' || true
echo
```
The watcher reads real forecast rainfall and the just-seeded report depths (Mathare 0.72 m dangerous, Mukuru 0.38 m impassable). Mathare's seeded depth is already `dangerous` (in `DANGER_KEYS`), so `/watch` will dispatch at least one alert regardless of today's rainfall — guaranteeing `/alerts` is non-empty. (Document this reasoning inline so a future reader knows the seed is deterministic given the seeded reports.)

### 4.2 Add a live `/alerts` check (non-fatal is fine, but assert non-empty)
In the verification block (step [7/9] area) add:
```
alerts_json="$(curl -s "$API_URL/alerts")"
echo "$alerts_json" | python3 -c 'import sys,json; d=json.load(sys.stdin); assert d.get("alerts"), "empty alerts"; print("    alerts count      =", len(d["alerts"]))' || { echo "    FAIL /alerts (empty or bad JSON)"; fail=1; }
```
Place it so a failure sets `fail=1` and trips the ship gate, matching the existing /reports check style.

**Note / verify at runtime:** `/watch` dispatch depends on the real `_latest_depth` reading the just-seeded reports. If the DynamoDB seed propagation lags the `/watch` call, Mathare's danger-category dispatch should still fire from the seeded report; but if `_latest_depth` falls back to the baseline (0.12 m, ankle) AND today's forecast is < 20 mm, no alert dispatches and `/alerts` would be empty. INSTRUCT THE IMPLEMENTER: after wiring, run `scripts/deploy.sh` and confirm `/alerts` returns ≥1 item; if it is empty, make the deploy call `/watch` AFTER a short settle (e.g. `sleep 3` after `/seed`) and re-check — do not fake an alert to pass the gate.

---

## 5. `web/replay.html` — 2024 Nairobi El Niño flood replay (NEW static page)

Static page that renders fully even if OUR API is down. It uses REAL Open-Meteo **ARCHIVE** data (no key, CORS-open). Follow DESIGN.md (light mode, Fira Sans/Fira Code, Phosphor SVG icons not emoji, risk color scale, a11y, responsive). Reuse `kinga.css` and `kinga.js` (for `Kinga.riskColor/riskLabel/fmtMm`).

### 5.1 Archive API URL shape (REAL data, verify the exact window at runtime)
Open-Meteo Historical Weather (archive) endpoint, per settlement:
```
https://archive-api.open-meteo.com/v1/archive?latitude={lat}&longitude={lon}&start_date=2024-04-01&end_date=2024-05-15&daily=precipitation_sum&timezone=Africa%2FNairobi
```
- Fetch once per settlement (Mathare `-1.2595,36.8580`, Mukuru `-1.3167,36.8667`), read `json.daily.time[]` and `json.daily.precipitation_sum[]` (mm/day).
- Date window covers the actual April–May 2024 Nairobi floods. **VERIFY AT RUNTIME** that the archive returns non-null `precipitation_sum` for this exact range at these coords (archive data has a few-days lag but 2024 is long past, so it should be complete). If the array has trailing `null`s, skip those days honestly rather than treating null as 0.

### 5.2 Honest day-by-day timeline (client-side rule, same threshold)
For each day with a real `precipitation_sum`:
- Show the date and the real rainfall (`Kinga.fmtMm`).
- Apply the SAME deterministic escalation threshold client-side: a day's rainfall `>= 20 mm` is the escalation trigger. Because depth is unknown/illustrative, label clearly: "Kinga Maji's rule would flag this day for escalation review (≥20 mm forecast over standing water)." For `< 20 mm` show "below the 20 mm escalation threshold." Color the day row by a simple honest mapping (e.g. ≥20 mm → amber/orange caution; the heaviest days → red) using the risk CSS vars, but ALWAYS show the mm number and a text label — color is never the sole signal (DESIGN.md).
- **Do NOT fabricate measured depths.** Explicitly state depth is illustrative where no measured photo existed. The replay demonstrates what the rainfall-side rule WOULD have flagged, using real archive rainfall only.

### 5.3 Honesty / citation block (required)
A visible note: "Retrospective replay using REAL daily rainfall from the Open-Meteo Historical Weather API (archive-api.open-meteo.com), {start_date}–{end_date}, for Mathare and Mukuru. Depth is illustrative — Kinga Maji computes real depth only from a photo with a known-height reference object; no measured depths are invented here." Cite Open-Meteo archive + the date range.

### 5.4 Resilience + optional API use
- All archive fetching is to the third-party Open-Meteo origin (independent of OUR API), so the page's core content renders without our backend. On archive fetch failure, show a graceful message ("Historical rainfall unavailable right now — this is a retrospective view; try again shortly."), never a blank page.
- `replay.html` need NOT call OUR API. If you add any call to OUR API (e.g. a small "latest live alerts" teaser), you MUST include the full fragmented sentinel pattern (`const API = '__API_URL__';` plain line + `const API_PLACEHOLDER = '__API' + '_URL__';` + `if (!API || API === API_PLACEHOLDER)` guard). If you do NOT call our API, do NOT add a bare `__API_URL__` token anywhere — keep the page free of the placeholder so deploy injection is a no-op for it. **Decision for the implementer:** keep replay.html purely archive-driven (no OUR-API call) to minimize risk; only add the sentinel if you add a live panel.
- Shared header + nav identical in structure to the other pages (brand water-drop + "Kinga Maji", nav Home · Check the water), PLUS a nav link to this replay page is optional on replay itself. No Leaflet, no map.

**Verify:** open `web/replay.html` locally (file://) — header, timeline scaffold, and citation render with NO network; with network, the real 2024 rainfall populates the timeline. Confirm 0 literal `__API_URL__` tokens unless a sentinel-guarded live panel was added.

---

## 6. `web/index.html` — alerts panel + replay links (ADDITIVE)

Keep the existing hero, how-it-works, worked example, live-now, trust sections and the existing `loadLive()`/`renderLive()` logic byte-identical. Keep the existing `const API = '__API_URL__';` + fragmented sentinel block exactly (the source line is a plain token; do not touch the sentinel).

### 6.1 Hero/section CTA to the replay
Add a secondary CTA button in the hero `.hero-cta` (next to "Check the water now"), styled `btn btn-ghost`, linking to `replay.html`, label "See the 2024 floods replayed" with a Phosphor icon (e.g. ClockCounterClockwise / Backward). aria-label on the icon control per DESIGN.md.

### 6.2 Nav link (both header navs: index.html and app.html)
Add a third nav item `<a href="replay.html">… 2024 replay</a>` with a Phosphor SVG icon (never emoji) and `.nav-label`, in BOTH `index.html` and `app.html` headers so navigation is consistent. Do not change `aria-current` on the existing items.

### 6.3 "Latest autonomous alerts" panel reading GET /alerts
Add a new `<section>` (e.g. after Live-now, before Trust) titled "Latest autonomous alerts" with a WarningCircle Phosphor icon. Add JS that reads `GET {API}/alerts` through the EXISTING fragmented sentinel guard:
```
async function loadAlerts() {
  if (!API || API === API_PLACEHOLDER) { /* preview empty state */ return; }
  try {
    const res = await fetch(API + '/alerts');
    const data = await res.json();
    renderAlerts(data.alerts || []);
  } catch (e) { /* graceful 'could not reach' empty state */ }
}
```
- `renderAlerts`: for each alert show settlement (with a `dot` colored by `Kinga.riskColor(category_key)`), `final_label`, depth (`Fira Code`), rainfall (`Kinga.fmtMm`), `Kinga.timeAgo(timestamp)` — NOTE the alert SK is `ALERT#<iso>`; strip the `ALERT#` prefix before passing to `timeAgo`/Date, or use a separate plain timestamp if you add one. **Decision:** display `(a.timestamp || '').replace('ALERT#','')` for the time. Show the `message` body (muted, smaller) so the judge sees the exact warning text.
- **Graceful empty state** (required): when `alerts` is empty OR in preview mode, show a friendly "No autonomous alerts yet. The watcher runs hourly and dispatches here." — never a blank panel, never an error-looking state in preview.
- Reuse the `.alerts` list CSS already defined in app.html's inline styles OR add equivalent minimal styles in index.html's `<style>`; match DESIGN.md tokens.
- Call `loadAlerts()` at the end of the inline script, alongside the existing `loadLive()`.

### 6.4 app.html may also show /alerts (optional, keep existing behavior)
app.html's existing "Latest alerts" panel currently reads `/reports` via `loadReports()`. KEEP that behavior (it is existing). OPTIONALLY add a second small block or augment to also fetch `/alerts` through the same fragmented guard already present in app.html. If you touch app.html's script, do NOT disturb the Leaflet init, the sentinel, or the existing `loadReports()` payload handling. Low priority — do only if time allows without risk.

**Verify:** open `index.html` locally — in preview mode the alerts panel shows its empty state (no error), everything else renders. After deploy, with real `/alerts` populated, the panel lists the seeded alert(s). Confirm the single `const API = '__API_URL__';` line and the fragmented sentinel are both still present and unmodified.

---

## 7. `scripts/deploy.sh` — upload replay.html + inject placeholder if present

The injection step [5/9] currently processes ONLY `$WEB_INDEX` and `$WEB_APP` explicitly; it does NOT glob `web/*.html`. The S3 BucketDeployment uploads the whole `web/` dir, so `replay.html` is uploaded automatically — BUT if replay.html ever contains a `const API = '__API_URL__';` line it would ship un-injected. Make deploy robust:

### 7.1 Add replay.html to the injection list
- Add `WEB_REPLAY="$ROOT/web/replay.html"` near the other path vars.
- In the step [5/9] python injection, pass `$WEB_REPLAY` as an additional argument so the same two replacements (`__API_URL__` → api, and the `const API = '...'` re-injection) run on it. The python loop already iterates `sys.argv[2:]`, so just append `"$WEB_REPLAY"` to the invocation. Guard against a missing file: either `[ -f "$WEB_REPLAY" ]` before including it, or make the python loop skip paths that don't exist. (If replay.html has no placeholder, both replacements are harmless no-ops.)

### 7.2 (From §4) add the `/watch` seed call and `/alerts` verification
Already specified in §4 — ensure both land in deploy.sh: the `POST /watch` after `/seed`, and the `/alerts` non-empty assertion in the verify block.

### 7.3 Do NOT change existing deploy behavior
Keep profile/region pinning, the two `cdk deploy` passes, the index/app injection, the hero-substring and leaflet live checks, and the retry loop unchanged. Additive only.

**Verify:** `bash -n scripts/deploy.sh` (syntax check). Full runtime verification happens in the dedicated deploy step.

---

## 8. Final cross-cutting verification (the implementer runs these before handing off)

1. `cd lambda && python3 -c "import handler"` — clean import.
2. `python3 engine/depth_engine.py` — engine self-check still prints its demo (engine untouched).
3. `cd cdk && . .venv/bin/activate && cdk synth KingaMajiStack` — synth OK; template has `AWS::Events::Rule` + `/alerts` + `/watch` routes.
4. `bash -n scripts/deploy.sh` — syntax OK.
5. Grep guards: confirm each of `web/index.html`, `web/app.html`, and (if it has a live panel) `web/replay.html` has exactly ONE `const API = '__API_URL__';` line and the `const API_PLACEHOLDER = '__API' + '_URL__';` sentinel, and NO contiguous `__API_URL__` inside any `if (... API ...)` comparison.
6. Confirm Leaflet SRI hashes in `app.html` are the exact pinned values (unchanged).
7. Open `web/replay.html` and `web/index.html` via file:// — both render fully with network OFF (static content + graceful empty states).

---

## 9. Runtime-only items the implementer MUST verify (cannot be confirmed by reading)

- **Open-Meteo ARCHIVE coverage** for 2024-04-01…2024-05-15 at both coords returns real non-null `precipitation_sum`. If some trailing days are null, skip them honestly. (Could not verify offline — hit the archive URL at build/verify time.)
- **`/watch` dispatches ≥1 alert on deploy** so `/alerts` is non-empty (see §4.2 note; add a short settle before `/watch` if the seed hasn't propagated — do not fabricate an alert).
- **EventBridge rule actually invokes** the Lambda on `/watch` and the synthetic event shape routes correctly (confirm by checking CloudWatch logs for one scheduled or manual invoke, or just rely on `POST /watch` returning `{"ok": true, "dispatched": N}`).
- **CloudFront serves replay.html** at `/replay.html` with 200 after deploy (BucketDeployment + invalidation). Optionally add a step-9 curl of `$CF_URL/replay.html` expecting 200 and a citation substring — non-fatal is acceptable but preferred as a gate.
- **Preview-guard still fetches live after deploy:** confirm 0 literal `__API_URL__` in the three uploaded pages and that `/alerts` data actually renders on the live home page.

---

## Ordered task list (checkboxes)

- [ ] 1. Define the alert schema/discriminator decisions (this doc §1) — no code, it governs §2/§6.
      Files: (reference only)
      Verify: n/a.
- [ ] 2. Edit `lambda/handler.py`: add constants, `_latest_depth`, `_alert_message`, `_watch_cycle`, `_alerts`, `_watch`; wire `/alerts` + `/watch` routes; add the `item_type == "alert"` filter in `_reports()`.
      Files: lambda/handler.py
      Verify: `cd lambda && python3 -c "import handler"`; offline monkeypatched `_watch_cycle` check produces an `item_type=="alert"` dict with a non-empty `message`; manual assert `/reports` filter drops alerts.
- [ ] 3. Edit `cdk/kinga_stack.py`: add `/alerts`+`/watch` routes; add EventBridge `rate(1 hour)` rule targeting the Lambda with the synthetic `/watch` event; add events/targets imports.
      Files: cdk/kinga_stack.py
      Verify: `cd cdk && . .venv/bin/activate && cdk synth KingaMajiStack`; template contains `AWS::Events::Rule` + both new routes.
- [ ] 4. Create `web/replay.html`: static 2024 El Niño replay using the Open-Meteo ARCHIVE API per settlement; honest day-by-day timeline with the ≥20 mm rule client-side; illustrative-depth + citation disclaimers; DESIGN.md compliant; renders with network off.
      Files: web/replay.html
      Verify: open via file:// with network OFF (renders) and ON (real 2024 rainfall populates); 0 literal `__API_URL__` unless a sentinel-guarded live panel added.
- [ ] 5. Edit `web/index.html`: hero CTA + nav link to replay.html; new "Latest autonomous alerts" panel reading `GET /alerts` via the existing fragmented sentinel with a graceful empty state.
      Files: web/index.html
      Verify: open via file:// (preview empty state shows, no errors); sentinel + single `const API='__API_URL__';` intact.
- [ ] 6. Edit `web/app.html`: add replay.html nav link (keep Leaflet SRI + sentinel + loadReports untouched); optionally surface `/alerts`.
      Files: web/app.html
      Verify: `grep` Leaflet SRI hashes unchanged; sentinel intact; file:// renders map/panels.
- [ ] 7. Edit `scripts/deploy.sh`: add `WEB_REPLAY`, include it in the step-5 injection (guarded for existence); add `POST /watch` after `/seed`; add `/alerts` non-empty assertion; optionally curl `$CF_URL/replay.html`.
      Files: scripts/deploy.sh
      Verify: `bash -n scripts/deploy.sh`.
- [ ] 8. Cross-cutting local verification (§8 1–7). Fix any failure before handoff.
      Files: (all above)
      Verify: all §8 commands pass locally; engine untouched; synth OK; guards/SRI intact.
