# Kinga Maji — Front-End Visual Redesign (Implementation Plan)

> Scope: **FRONT-END ONLY.** The app is already LIVE on AWS and passing the ship gate.
> Do NOT touch `lambda/handler.py`, the engine, CDK backend resources, API routes, or payload shapes.
> This plan restyles the UI to `DESIGN.md`, splits the single page into a landing page +
> tool page, and updates `deploy.sh` so the API-URL placeholder is injected into BOTH pages.

## Ground truth confirmed by reading the code

- `web/index.html` is currently the ONLY page: a dark, plain single tool page (map + report form +
  trace + alerts). It carries the placeholder `const API = '__API_URL__';`.
- `DESIGN.md` is authoritative: **light mode**, organic green base, risk-driven color scale,
  **Fira Sans** (UI/headings) + **Fira Code** (numbers/trace), **Phosphor** icons (never emoji),
  accessibility checklist, and page structure: `index.html` = HOME, `app.html` = tool, shared header.
- Engine reference keys (DO NOT rename — map to the engine) are exactly:
  `doorframe` (2.03 m), `jerrycan_20l` (0.46 m), `car_tyre` (0.63 m), `brick_course` (0.075 m),
  `matatu_wheel` (0.70 m).
- Engine category keys (drive risk color + MUST also show label + metres): `nuisance`, `ankle`,
  `impassable_boda`, `dangerous`, `evacuate` (plus `error`/`unknown` → neutral grey).
  DESIGN.md risk tokens map: nuisance→`--risk-nuisance`, ankle→`--risk-ankle`,
  **impassable_boda→`--risk-impassable`**, dangerous→`--risk-dangerous`, evacuate→`--risk-evacuate`.
- API base is used as `API + '/analyze'`, `API + '/reports'`, `API + '/seed'`. These calls and all
  payload shapes (`{settlement, reference_object, image_base64}` and `{demo, settlement, reference_object}`)
  stay **byte-for-byte identical**.
- `cdk/kinga_stack.py` deploys the WHOLE `web/` dir (`s3deploy.Source.asset(WEB_ASSET)`) with
  `default_root_object="index.html"`. So `app.html` uploads automatically once it exists; **no CDK
  change is needed or allowed.** Only `deploy.sh`'s injection step must be extended to `app.html`.
- `deploy.sh` injects the API URL into `web/index.html` ONLY, via (a) literal `__API_URL__` replace
  and (b) regex `const API = '...';`. This MUST be extended to also process `web/app.html`.

---

## Implementation steps (ordered by dependency)

- [ ] 1. **Create the shared CSS token/base file `web/kinga.css`** implementing DESIGN.md.
      Define `:root` custom properties for all color tokens (`--color-primary #059669`,
      `--color-on-primary`, `--color-secondary`, `--color-background #ECFDF5`,
      `--color-foreground #064E3B`, `--color-card`, `--color-card-foreground`, `--color-muted`,
      `--color-muted-foreground`, `--color-border #A7F3D0`, `--color-ring`) and the RISK SCALE
      (`--risk-nuisance #10B981`, `--risk-ankle #FBBF24`, `--risk-impassable #F97316`,
      `--risk-dangerous #DC2626`, `--risk-evacuate #7F1D1D`, `--color-on-risk #FFFFFF`,
      plus `--risk-neutral #475569` for error/unknown).
      Add base typography (`font-family: 'Fira Sans'`; a `.mono`/`code`/trace rule → `'Fira Code'`),
      light-mode body (`background: var(--color-background); color: var(--color-foreground)`),
      shared `.header`/`.brand`/`.nav` styles, `.btn`/`.btn-primary`/`.btn-ghost` with
      `cursor: pointer` and `transition: 150–300ms`, card styles (border-radius 16–24px, soft
      shadow, `border: 1px solid var(--color-border)`), visible `:focus-visible` outline using
      `--color-ring`, and a `@media (prefers-reduced-motion: reduce)` block that disables
      transitions/animations. Include responsive rules verified at 375/768/1024/1440 (mobile-first;
      container max-width + fluid padding; nav collapses gracefully on 375).
      Files: `web/kinga.css`
      Verify: `python3 -c "import pathlib,re; s=pathlib.Path('web/kinga.css').read_text(); assert '--risk-impassable' in s and '--color-background' in s and 'prefers-reduced-motion' in s and 'Fira Code' in s"`
      and open `web/kinga.css` in a browser-linked page (step 4) to confirm it loads.

- [ ] 2. **Add a tiny shared JS helper `web/kinga.js`** for the risk-scale mapping reused by BOTH
      pages (single source of truth so colors/labels never drift).
      Export (via globals, no bundler) a `CATEGORY` map keyed by engine `category_key` →
      `{ cssVar, label }` using the EXACT keys (`nuisance`, `ankle`, `impassable_boda`, `dangerous`,
      `evacuate`, `error`, `unknown`), a `riskColor(key)` returning the CSS custom property value
      (falling back to `--risk-neutral`), and a `timeAgo(iso)` copied verbatim from the current
      `index.html`. Do NOT change any payload or endpoint logic here — presentation only.
      Files: `web/kinga.js`
      Verify: `python3 -c "import pathlib; s=pathlib.Path('web/kinga.js').read_text(); assert all(k in s for k in ['nuisance','ankle','impassable_boda','dangerous','evacuate']) and 'riskColor' in s and 'timeAgo' in s"`

- [ ] 3. **Create `web/app.html` by MOVING the current tool out of `index.html` and restyling it.**
      Copy the ENTIRE current `index.html` body (map, report form, result card, trace, latest
      alerts) and all its `<script>` logic into `web/app.html`, then:
      (a) keep `const API = '__API_URL__';` placeholder intact (do NOT hardcode a URL);
      (b) keep ALL fetch calls (`API + '/analyze'`, `API + '/reports'`) and both payload shapes
      byte-for-byte identical;
      (c) keep the settlement picker (`Mathare`, `Mukuru`) and the reference-object picker with the
      EXACT five keys/values (`doorframe`, `jerrycan_20l`, `car_tyre`, `brick_course`,
      `matatu_wheel`) — do not rename, reorder-break, or invent;
      (d) replace inline dark CSS with `<link rel="stylesheet" href="kinga.css">` + Fira fonts
      `@import`/`<link>` + Leaflet CSS/JS CDN + Phosphor icons CDN;
      (e) restyle: shared header (water-drop Phosphor icon + "Kinga Maji" brand, nav Home→`index.html`
      + "Check the water" current page, NO login); result card border/background colored by
      `category_key` via `riskColor()` AND always showing `final_label` + `depth_m` in metres +
      `advice`; the deterministic `trace` rendered in **Fira Code** as evidence; Leaflet markers for
      Mathare/Mukuru colored by latest risk category via the scale; the latest-alerts panel from
      `/reports` using `riskColor()` with a **dot + label + metres** (color never sole signal);
      (f) use `web/kinga.js` for `riskColor`/`CATEGORY`/`timeAgo`;
      (g) Phosphor SVG icons only (WarningCircle for alerts, MapPin for settlements, ArrowRight on
      CTA) — never emoji; icon-only controls get an accessible name; decorative icons `aria-hidden`.
      Files: `web/app.html`
      Verify: `python3 -c "import pathlib; s=pathlib.Path('web/app.html').read_text(); assert \"const API = '__API_URL__';\" in s; assert all(k in s for k in ['doorframe','jerrycan_20l','car_tyre','brick_course','matatu_wheel']); assert \"/analyze\" in s and \"/reports\" in s; assert 'kinga.css' in s and 'Fira+Code' in s.replace(' ','+')"`
      and load `web/app.html?API=` locally (preview mode) to confirm the map, form, demo button, and
      graceful no-API messaging render in light theme.

- [ ] 4. **Create the NEW `web/index.html` landing/home page per DESIGN.md** (overwrite the old tool
      page). Structure, Trust & Authority + Conversion pattern:
      - **Shared header**: water-drop Phosphor brand + "Kinga Maji", nav Home (current) +
        "Check the water" → `app.html`. NO login.
      - **Hero**: headline exactly "Kinga Maji — the flood warning that shows its working"; one-line
        mission naming **Mathare and Mukuru**; primary CTA "Check the water now" → `app.html`
        (ArrowRight Phosphor icon); optional decorative wave SVG `aria-hidden="true"` (static under
        reduced-motion).
      - **How it works** strip: the provable mechanic — photo → model reads **PIXELS ONLY** →
        deterministic engine computes **metres** → rainfall fusion → warning; emphasize
        "every number is computed and traced, never guessed."
      - **Live now** proof section: `fetch(API + '/reports')` and render current reports (settlement,
        `depth_m`, category label) with risk-scale colors via `web/kinga.js`; **MUST** wrap in
        try/catch and degrade to a friendly empty/offline state if the API is unreachable or still in
        placeholder preview mode (mirror the current page's `__API_URL__` guard). Color never sole
        signal — show label + metres.
      - **Trust row**: built on AWS (Bedrock, Lambda, DynamoDB, S3+CloudFront); Social Good / climate
        resilience; community lane. Phosphor icons, no emoji.
      - **Footer note**: it does NOT replace official emergency services.
      Include `const API = '__API_URL__';` placeholder (same guard pattern as the tool page) so
      deploy injects it; link `kinga.css`, `kinga.js`, Fira fonts, Phosphor CDN.
      Files: `web/index.html`
      Verify: `python3 -c "import pathlib; s=pathlib.Path('web/index.html').read_text(); assert \"const API = '__API_URL__';\" in s; assert 'app.html' in s; assert 'Mathare' in s and 'Mukuru' in s; assert '/reports' in s and 'try' in s and 'catch' in s; assert 'shows its working' in s"`
      and load locally to confirm hero/how-it-works/live-proof/trust/footer render in light theme and
      the live-proof section shows the friendly empty state in preview mode (no uncaught errors).

- [ ] 5. **Update `scripts/deploy.sh` so the API URL is injected into `web/app.html` too.**
      In step `[5/9]` of `deploy.sh`: add `WEB_APP="$ROOT/web/app.html"` beside the existing
      `WEB_INDEX`, and either (preferred) run the SAME inline python injection block over BOTH files
      by iterating, or make the heredoc accept multiple paths. The injection MUST, for each file,
      do both replacements already used: `html.replace("__API_URL__", api)` and
      `re.sub(r"const API = '[^']*';", "const API = '%s';" % api, html, count=1)`. Keep the block
      idempotent and preserve the placeholder mechanism in source (never commit the real
      execute-api URL). Do NOT alter CDK steps — the whole `web/` dir already uploads via
      `Source.asset`.
      Optionally extend the `[9/9]` CloudFront verification to also fetch `$CF_URL/app.html` and
      assert it contains the injected `$API_URL` and no residual `__API_URL__` (nice-to-have proof;
      keep the existing root `index.html` checks).
      Files: `scripts/deploy.sh`
      Verify: `bash -n scripts/deploy.sh` (syntax OK) and
      `python3 -c "import pathlib; s=pathlib.Path('scripts/deploy.sh').read_text(); assert 'app.html' in s"`
      Then dry-reason the injection on a copy:
      `cp web/app.html /tmp/app.copy.html && python3 - /tmp/app.copy.html 'https://example.execute-api/prod' <<'PY'
import re,sys; p,a=sys.argv[1],sys.argv[2]; h=open(p).read(); h=h.replace('__API_URL__',a); h=re.sub(r"const API = '[^']*';","const API = '%s';"%a,h,count=1); open(p,'w').write(h); assert a in open(p).read() and '__API_URL__' not in open(p).read(); print('inject ok')
PY`

- [ ] 6. **Accessibility + responsive pass across BOTH pages** (per DESIGN.md checklist).
      Confirm, fixing where needed: Phosphor SVG icons only (grep for emoji / ensure none used as
      structural icons); `cursor: pointer` on every clickable; visible `:focus-visible` state; hover
      transitions 150–300ms; text contrast ≥ 4.5:1 (deep-green ink on light; white on risk-red —
      verify `--risk-ankle #FBBF24` amber uses deep-green ink, not white, where text sits on it);
      `prefers-reduced-motion` disables the hero wave animation and transitions; layouts verified at
      375/768/1024/1440; and color is NEVER the sole risk signal anywhere (result card, map popups,
      alerts, live-proof all show label + metres alongside color).
      Files: `web/index.html`, `web/app.html`, `web/kinga.css`
      Verify: `python3 -c "import pathlib,glob; txt=''.join(pathlib.Path(p).read_text() for p in ['web/index.html','web/app.html','web/kinga.css']); import re; assert not re.search(r'[\U0001F300-\U0001FAFF\u2600-\u27BF]', txt), 'emoji found'; assert 'prefers-reduced-motion' in txt and 'focus-visible' in txt and 'cursor' in txt"`
      and manual check at the four breakpoints in a browser.

---

## Note on verification after implementation

After these steps, the implementer must: deploy with `bash scripts/deploy.sh` (simi-ops profile,
us-east-1 — the script is idempotent and re-uploads via CDK `BucketDeployment`), then live-curl-verify
that CloudFront serves the new landing page at `/` and the restyled tool at `/app.html`, that BOTH have
the real injected API URL (and NO residual `__API_URL__`), and that `/reports` powers the "Live now"
section. Implementation, deploy, and live curl-verification follow this plan.
