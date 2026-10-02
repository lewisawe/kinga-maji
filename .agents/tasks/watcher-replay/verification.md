# Local Verification — Autonomous Watcher + 2024 Flood Replay

First iteration (no `review.json` present). Both additive improvements implemented
from the plan. All commands below were run locally; **no deploy** was performed
(a later dedicated step owns deploy + live verification).

## 1. Engine self-check (must still pass, engine untouched)

```
$ python3 engine/depth_engine.py
```
Result: **PASS** — printed the doorframe demo trace unchanged:
`Depth = 0.95 m -> Evacuate`, then `FINAL: Evacuate (escalated by forecast rain)`.
`engine/depth_engine.py` has zero edits (`git diff` empty for that file).

## 2. Handler import check (lazy boto3 — imports without creds)

```
$ cp engine/depth_engine.py lambda/depth_engine.py   # deploy vendors this; needed for local import
$ cd lambda && python3 -c "import handler"
```
Result: **IMPORT_OK** — module imports cleanly with no AWS credentials.
`boto3.dynamodb.conditions.Key` is imported lazily inside `_latest_depth`, so the
module import never touches boto3.

### 2b. Offline watcher-cycle smoke test (monkeypatched, no network/DynamoDB)

```
handler.rainfall      -> (25.0, True)   # patched
handler._latest_depth -> (0.12, 'test') # patched
handler._persist      -> collect in a list  # patched
out = handler._watch_cycle()
```
Result: **OFFLINE_WATCH_OK** — dispatched 2 alerts. Each dispatched dict has
`item_type == "alert"`, a `timestamp` prefixed `ALERT#`, `escalated is True`
(25 mm over 0.12 m ankle depth escalates to `impassable_boda`), a non-empty
`trace` list, and the exact message body:
```
KINGA MAJI FLOOD ALERT — Mathare. Impassable for boda (escalated by forecast rain).
Standing water ~0.12 m, forecast rain next 24h 25.0 mm. Motorcycles stall/stall-risk.
Avoid crossing. This is an automated warning; it does not replace official emergency services.
```
Also verified the `_reports()` discriminator drops `item_type == "alert"` items
(REPORTS_FILTER_OK).

### 2c. Existing routes/shapes unchanged

```
$ python3 -c "...handler.handler(/health GET)... /404 fallback... _resp shape..."
```
Result: **ROUTES_AND_SHAPES_OK** — `GET /health` -> `{"ok": true}`, unknown path
-> 404, `_resp` keeps open-CORS headers and `statusCode`. `git diff lambda/handler.py`
shows **0 deletions, 193 insertions** (pure additive; existing payloads byte-identical).

## 3. CDK synth (additive EventBridge rule + 2 routes)

```
$ cd cdk && . .venv/bin/activate
$ CDK_DEPLOY_ACCOUNT=888577033943 CDK_DEPLOY_REGION=us-east-1 \
    ./node_modules/.bin/cdk synth KingaMajiStack
```
Result: **EXIT=0**. Synthesized template contains:
- `AWS::Events::Rule` count = **1**, schedule `rate(1 hour)`.
- `AWS::ApiGatewayV2::Route` count = **6** (was 4; added `GET /alerts`, `POST /watch`).
- EventBridge target `Input = {"rawPath":"/watch","requestContext":{"http":{"method":"POST"}}}`.
- Exactly **1** `events.amazonaws.com` `lambda:InvokeFunction` permission (auto-created).
- Env account pinned `888577033943` / `us-east-1` (unchanged in `cdk/app.py`).

## 4. Deploy script syntax

```
$ bash -n scripts/deploy.sh
```
Result: **SYNTAX_OK**. Additive changes only:
- `WEB_REPLAY` path var; step [5/9] injection now also processes `replay.html`
  (loop skips missing files; replacements are no-ops when no placeholder present).
- Step [6b]: `sleep 3` then `POST /watch` after `/seed` to seed one real alert.
- Verify block: non-empty `/alerts` assertion (sets `fail=1` on empty/bad JSON).
- Step [9/9]: `CloudFront /replay.html` -> 200 + archive citation substring gate.

## 5. Guard / sentinel / SRI / keys (grep audit, §8.5–8.6)

| Page | `const API = '__API_URL__';` | fragmented sentinel | literal `__API_URL__` | contiguous token in a guard |
|------|------------------------------|---------------------|------------------------|------------------------------|
| index.html | 1 | 1 | 1 (the plain assignment only) | 0 |
| app.html | 1 | 1 | 1 (the plain assignment only) | 0 |
| replay.html | 0 | 0 | 0 (archive-only, no placeholder) | 0 |

- `app.html` Leaflet **1.9.4** SRI hashes intact: JS `sha256-20nQCchB9co0qIjJZRGuk2/Z9VM+kNiyxNV1lvTlZBo=` (1), CSS `sha256-p4NxAoJBhIIN+hmNHrzRCf9tD/miZyoHS5obTRR9BMY=` (1).
- 5 reference keys present in `app.html` (`doorframe`, `jerrycan_20l`, `car_tyre`, `brick_course`, `matatu_wheel`).
- replay nav links: index.html 2 (nav + hero CTA), app.html 1 (nav), replay.html 1 (self nav).

Note: `web/index.html` and `web/app.html` were committed with a real injected URL
from a prior deploy. The source line was restored to the required
`const API = '__API_URL__';` placeholder. This is behavior-preserving at the live
layer: `scripts/deploy.sh` re-injects the real URL via both
`.replace("__API_URL__", api)` and `re.sub(r"const API = '[^']*';", ...)`, so the
deployed pages still fetch the live API. 0 literal `__API_URL__` remain post-deploy.

## 6. HTML well-formedness

Python `html.parser` tag-balance check on all three pages: **OK** (no stray close
tags, no unclosed non-`html`/`body` tags).

## 7. Runtime-only checks performed at build time

- **Open-Meteo ARCHIVE coverage** for 2024-04-01…2024-05-15: hit the live archive
  endpoint for both coords. Mathare = 45/45 non-null days, 2 days ≥20 mm
  (2024-04-26 = 26.9 mm, 2024-04-28 = 20.6 mm — the real El Niño flood peak).
  Mukuru = 45/45 non-null days, 1 day ≥20 mm. No trailing nulls that needed skipping,
  but the client still skips any null day honestly.

## Items deferred to the dedicated deploy step (cannot confirm offline)

- `POST /watch` dispatches ≥1 alert on deploy so `/alerts` is non-empty (seed
  Mathare 0.72 m `dangerous` guarantees dispatch regardless of today's forecast;
  `sleep 3` added before `/watch` so the seed propagates).
- EventBridge rule actually invokes the Lambda on the synthetic `/watch` event.
- CloudFront serves `replay.html` with 200 + citation after deploy.
- 0 literal `__API_URL__` in the three uploaded pages post-injection; `/alerts`
  data renders on the live home page.
