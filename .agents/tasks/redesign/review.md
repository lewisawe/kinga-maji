# Front-end redesign to DESIGN.md — landing page + restyled tool

The change (commit `af51b18`) splits Kinga Maji's single dark tool page into a light-mode landing page (`index.html`) and a restyled tool page (`app.html`) built on the DESIGN.md system, backed by two new shared assets (`kinga.css` tokens, `kinga.js` risk-scale helper), and extends `deploy.sh` to inject the API URL into both pages. It is strictly front-end: no backend, engine, CDK, API route, payload, or reference-key change. Verified against the plan and DESIGN.md, every blocking requirement holds — the five reference keys and all API calls/payloads are byte-for-byte identical to the previous page, both pages carry the exact `const API = '__API_URL__';` placeholder with no hardcoded execute-api URL anywhere in source, and deploy.sh now injects both files idempotently.

Watch for: nothing blocking. One cosmetic observation (disabled-button cursor is `progress`, not `not-allowed`) is noted but is not a DESIGN.md requirement. **Verdict**: APPROVED

## High-level view

The payload/endpoint contract is preserved exactly. `app.html`'s `/analyze` POST sends `{settlement, reference_object, image_base64}`, the demo sends `{demo, settlement, reference_object}`, and `/reports` is a GET — identical strings, methods, headers, and body construction to the prior `index.html` (confirmed by diffing the old file's API lines against the new ones). This was the highest-risk area and it is clean.

The API placeholder mechanism is intact and consistent across both pages, which is what `deploy.sh` depends on. Each page has exactly one `const API = '__API_URL__';` line that the deploy regex targets, the literal `__API_URL__` appears in each page's preview-mode guard, and no real execute-api URL exists in source. `deploy.sh` [5/9] now iterates `index.html` and `app.html` through the same two replacements (literal replace + `const API` regex, `count=1`), and [9/9] additionally curls `/app.html` to assert the injected URL and absent placeholder. Idempotency is preserved.

The five engine reference keys (`doorframe`, `jerrycan_20l`, `car_tyre`, `brick_course`, `matatu_wheel`) survive unchanged in `app.html`'s picker, and the category keys live in one place (`kinga.js` `CATEGORY`) with the exact engine keys plus `error`/`unknown` falling back to neutral grey. Color is never the sole risk signal: the result card, map popups, live-now cards, and alerts all render the label and the depth in metres alongside the color.

The landing page matches the DESIGN.md Trust & Authority + Conversion pattern: hero headline verbatim, Mathare and Mukuru named, CTA "Check the water now" → `app.html`, a four-step how-it-works strip emphasizing pixels-only/deterministic-metres, a "Live now" `/reports` section wrapped in try/catch with a preview-mode guard and friendly empty/offline states, an AWS + Social-Good + community trust row, and the emergency-services footer note.

Accessibility and scope are satisfied: Phosphor SVG icons throughout (no emoji anywhere in `web/`), visible `:focus-visible` ring, `cursor: pointer` on clickables, transitions at 220ms (inside 150–300ms), a `prefers-reduced-motion` block, responsive breakpoints with graceful nav collapse at 420px, dark ink on the amber swatch for contrast, and no login/auth added. Only the five front-end files changed.

<details>
<summary>Issues (0 blocking, 1 cosmetic)</summary>

1. **Disabled-button cursor** (cosmetic, non-blocking) — `.btn:disabled` uses `cursor: progress` rather than `not-allowed`. DESIGN.md requires `cursor-pointer` on clickable elements (satisfied) but does not mandate a disabled cursor; `progress` is defensible during the async analyze call. No action required.

</details>

<details>
<summary>Details</summary>

### Payload and endpoint fidelity (blocking requirement — PASS)

Diffing the previous `index.html` API lines against the new `app.html`:

```
old index.html                         new app.html
const API = '__API_URL__';             const API = '__API_URL__';
fetch(API + '/analyze', {              fetch(API + '/analyze', {
  method: 'POST',                        method: 'POST',
  headers {'Content-Type': ...}          headers {'Content-Type': ...}
  body: JSON.stringify(payload)          body: JSON.stringify(payload)
{settlement, reference_object,         {settlement, reference_object,
 image_base64}                          image_base64}
{demo, settlement, reference_object}   {demo, settlement, reference_object}
fetch(API + '/reports')                fetch(API + '/reports')
```

Every URL, method, header, and body shape matches. There is no `/seed` call in either the old or new front-end (seed is a deploy-time step), so nothing was dropped. This is the change's biggest risk surface and it is byte-for-byte identical — no blocking finding.

### API placeholder and deploy injection (blocking requirement — PASS)

`grep -c "__API_URL__"` returns 2 for `index.html` and 3 for `app.html`; the extra hits are the preview-mode guards (`if (!API || API === '__API_URL__')`) and a comment, not stray real URLs. The regex-targeted line `const API = '__API_URL__';` appears exactly once in each page (index.html:246, app.html:201), which is what `re.sub(..., count=1)` expects. A repo-wide grep for `execute-api` / `amazonaws.com/(prod|dev)` across `web/` and `deploy.sh` returns nothing — no real URL is committed.

`deploy.sh` [5/9] was rewritten to pass `$API_URL` plus both file paths into one python block that loops `for path in sys.argv[2:]`, applying `html.replace("__API_URL__", api)` and the `const API` regex to each. Because both replacements are find-and-overwrite, a second pass is a no-op — idempotency holds. [9/9] now curls `$CF_URL/app.html`, asserts HTTP 200, asserts the injected `$API_URL` is present, and keeps the root `index.html` placeholder-absent checks. This satisfies the plan's requirement that injection reach `app.html` too.

### Reference keys and risk scale (PASS)

`app.html`'s reference-object `<select>` carries all five keys with their known heights (doorframe 2.03 m, jerrycan_20l 0.46 m, car_tyre 0.63 m, brick_course 0.075 m, matatu_wheel 0.70 m) — unchanged from the original. The settlement picker keeps Mathare and Mukuru. `kinga.js` centralizes the `CATEGORY` map on the exact engine keys (`nuisance`, `ankle`, `impassable_boda`, `dangerous`, `evacuate`, `error`, `unknown`), with `error`/`unknown` → `--risk-neutral`, matching DESIGN.md's token mapping (notably `impassable_boda → --risk-impassable`). The result card renders `depth_m` (fixed to 2 dp + " m"), `final_label`, `advice`, and the full `trace` in a `.trace.mono` ordered list rendered in Fira Code.

### Landing page structure (PASS)

Hero headline is exactly "Kinga Maji — the flood warning that shows its working" (split across a text node and an `.accent` span, which still reads verbatim in the DOM). The lead names Mathare and Mukuru; the badge and footer name them too (4 occurrences each). CTA "Check the water now" links to `app.html` with an ArrowRight Phosphor icon. The how-it-works strip is four steps (photo → pixels-only → deterministic metres → rainfall+warning) with a provable-note reinforcing "computed and traced, never guessed." The "Live now" section fetches `API + '/reports'` inside `try/catch`, guards preview mode (`API === '__API_URL__'` → friendly message), degrades to an empty state on error or no reports, and renders each card with a color dot, settlement, depth in metres, and label. The trust row covers AWS (Bedrock/Lambda/DynamoDB/S3+CloudFront), Social Good / climate resilience, and community. The footer states it does not replace official emergency services.

### Accessibility and scope (PASS)

Emoji scan across all four `web/` files finds none; icons are inline Phosphor SVG paths. `kinga.css` provides a visible `:focus-visible` outline using `--color-ring`, `cursor: pointer` on nav/buttons/selects, transitions via `--ease: 220ms` (within 150–300ms), and a `prefers-reduced-motion` block that collapses animation/transition durations. Responsive rules exist at 768px and 420px (nav labels hide, icons shrink) in addition to per-page grid breakpoints at 640/760/900/920/980px. The amber `--risk-ankle` swatch is paired with dark ink (`riskInk` → `#3F2D00`) so text clears 4.5:1 rather than failing with white. Color is never the sole risk signal anywhere. No login/auth was added — the only "login" string is trust-row copy ("no login") and "authorities" in the footer. `git show --name-only` confirms only `scripts/deploy.sh`, `web/app.html`, `web/index.html`, `web/kinga.css`, `web/kinga.js` changed; `lambda/handler.py`, the engine, CDK, and API routes are untouched.

</details>

<details>
<summary>Files changed</summary>

- `web/index.html` — rewritten as the DESIGN.md landing page (hero, how-it-works, live-now, trust, footer); keeps `const API` placeholder.
- `web/app.html` — new; the prior tool moved here and restyled; API calls/payloads/reference keys unchanged.
- `web/kinga.css` — new shared token/base stylesheet (colors, risk scale, typography, header/nav/btn/card, focus, reduced-motion, responsive).
- `web/kinga.js` — new shared risk-scale helper (`CATEGORY`, `riskColor`, `riskInk`, `riskLabel`, `timeAgo`).
- `scripts/deploy.sh` — [5/9] injects both pages idempotently; [9/9] verifies `/app.html` is served + injected.

Full diff: `git show af51b18`.

</details>
