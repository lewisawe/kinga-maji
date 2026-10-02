# Kinga Maji — Design System (DESIGN.md)

> Source: ui-ux-pro-max design-system generator ("climate resilience civic safety flood warning community tool"),
> adapted for a flood-WARNING instrument (not a wellness/eco brand). Accessibility-checked.
> Authoritative styling contract for the home page and the app page. Light mode.

## Design intent
A calm, trustworthy civic tool that turns into an instrument of urgency when the water is dangerous.
The base is organic + green (resilience, community, nature). **Risk severity drives color** — the UI
must *show* danger, not just describe it. Avoid the generator's flagged anti-pattern: "greenwashing +
no real data." Every surface that claims a risk shows the real measured number and its trace.

## Pattern
Trust & Authority + Conversion (civic adaptation):
1. Hero — mission + credibility (named settlements, "shows its working")
2. How it works — the provable mechanic made visible (photo → pixels → deterministic metres → warning)
3. Live proof — real current /reports pulled onto the page
4. Clear CTA path — "Check the water now" → app page

## Color tokens (light mode)
```
--color-primary:        #059669   /* resilience green — brand, primary buttons */
--color-on-primary:     #FFFFFF
--color-secondary:      #10B981
--color-background:     #ECFDF5   /* soft green-tinted canvas */
--color-foreground:     #064E3B   /* deep green ink */
--color-card:           #FFFFFF
--color-card-foreground:#064E3B
--color-muted:          #E8F1F3
--color-muted-foreground:#475569
--color-border:         #A7F3D0
--color-ring:           #059669

/* RISK SCALE — these drive category UI (the instrument) */
--risk-nuisance:        #10B981   /* green  — passable */
--risk-ankle:           #FBBF24   /* amber  — caution */
--risk-impassable:      #F97316   /* orange — impassable for boda */
--risk-dangerous:       #DC2626   /* red    — dangerous current */
--risk-evacuate:        #7F1D1D   /* dark red — evacuate */
--color-on-risk:        #FFFFFF
```
Rule: a result card, a map marker, and the alert panel all take their color from the engine's
`category_key` via this scale. Green when safe, red/dark-red when dangerous. Severity is felt instantly.

## Typography
- Headings + UI: **Fira Sans** (300/400/500/600/700)
- Numbers, depth values, the deterministic trace: **Fira Code** (monospace — makes the arithmetic read as evidence)
```
@import url('https://fonts.googleapis.com/css2?family=Fira+Code:wght@400;500;600;700&family=Fira+Sans:wght@300;400;500;600;700&display=swap');
```

## Effects
- Rounded corners 16–24px, organic/soft cards, natural shadows (low spread, soft).
- Transitions 150–300ms on hover/press. No layout-shifting transforms.
- Optional flowing SVG wave shape in the hero (decorative, aria-hidden).

## Icons — Phosphor (SVG, never emoji)
- Water drop → brand/mechanic · Shield → "kinga"/protection · MapPin → settlements ·
  WarningCircle → risk/alerts · House → home nav · ArrowRight → CTA.
- Decorative icons beside visible text: aria-hidden="true". Icon-only controls: accessible name.

## Accessibility (pre-delivery checklist — must pass)
- [ ] No emoji as icons (Phosphor SVG only)
- [ ] cursor-pointer on all clickable elements
- [ ] Hover/focus states, 150–300ms transitions, visible keyboard focus
- [ ] Text contrast ≥ 4.5:1 (deep-green ink on light; white on risk-red)
- [ ] prefers-reduced-motion respected (no auto motion; static waves)
- [ ] Responsive at 375 / 768 / 1024 / 1440 px
- [ ] Color never the SOLE signal — every risk also shows its label + metres + trace

## Page structure
- `index.html` — HOME / landing (hero, how-it-works, live proof via /reports, CTA → app)
- `app.html` — the tool (Leaflet map, settlement + reference picker, photo upload, risk-colored result + full trace, latest alerts)
- Shared header: brand (water-drop + "Kinga Maji") + nav (Home · Check the water). No login anywhere.


---
## Known fix (2026-10-02): preview-guard inversion
deploy.sh does a blanket `html.replace("__API_URL__", api)`, which also rewrote the token inside the
preview-mode guard comparisons, inverting them so the LIVE site always took the preview branch and never
fetched the API. Fixed by comparing against a FRAGMENTED sentinel the blanket replace cannot match:
`var API_PLACEHOLDER = '__API' + '_URL__';` then `if (!API || API === API_PLACEHOLDER)`. The `const API = '__API_URL__'`
assignment line stays a plain token so deploy.sh still injects the real URL. Applies to all 3 guards
(index loadLive, app analyze, app alerts). Rule for future front-end edits: never compare against a literal
`__API_URL__` token — always use the fragmented sentinel.


## Known fix (2026-10-02): Leaflet map "Map unavailable offline" = stale SRI hash
Symptom: app.html map showed the catch-fallback "Map unavailable offline." Root cause: the page pinned
leaflet@1.9.4 but carried the leaflet **1.9.3** integrity hash (sha256-o9N1jGDZ...). The browser's
Subresource Integrity gate computed a different hash for the 1.9.4 file and REFUSED to execute leaflet.js,
so `L` was undefined and `L.map()` threw into the catch. Fix: set the integrity to the real 1.9.4 hash
`sha256-20nQCchB9co0qIjJZRGuk2/Z9VM+kNiyxNV1lvTlZBo=` (verified: the live leaflet.js file hash == this value).
Rule: when pinning a CDN asset with SRI, the integrity hash MUST match that exact version's file. If you bump
the version, recompute the hash (`curl -s <url> | openssl dgst -sha256 -binary | openssl base64`), or drop the
integrity attr. The CSS hash (p4Nx...) was already correct.

Also: deploy.sh step [9/9] verifier can report false "leaflet missing"/"hero missing" FAILs right after an
invalidation when CloudFront briefly serves a propagating body — a verifier timing artifact, not a site fault.
Tightened to retry both pages together; the authoritative check is a direct curl of the live URL after settle.
