# Kinga Maji — Front-end Redesign Deploy Verification

Deploy run under: `AWS_PROFILE=simi-ops AWS_DEFAULT_REGION=us-east-1 bash scripts/deploy.sh`
CDK deployed via the local pinned CLI (`cdk/node_modules/.bin/cdk` = 2.1144.0). Backend untouched.

## Live URLs

| Page | URL |
|------|-----|
| Home page | https://d3eujpe11u21wb.cloudfront.net |
| Tool page | https://d3eujpe11u21wb.cloudfront.net/app.html |
| Backend API | https://dh0959qwna.execute-api.us-east-1.amazonaws.com |

## Check 1 — Home page (CloudFront root)

- **HTTP code:** `200`
- **Hero headline grep** (`the flood warning that shows its working`): FOUND (confirms NEW home page)
- **Leftover `__API_URL__` placeholder:** `0` matches (none — correctly injected)
- **Real execute-api URL injected** (grep `execute-api`): FOUND
  - `const API = 'https://dh0959qwna.execute-api.us-east-1.amazonaws.com'`

```
HTTP code: 200
-- hero headline grep:
the flood warning that shows its working
-- leftover __API_URL__ placeholder (expect none): 0
-- execute-api injected grep: execute-api.us-east-1.amazonaws.com
-- full injected API line: const API = 'https://dh0959qwna.execute-api.us-east-1.amazonaws.com'
```

## Check 2 — Tool page (/app.html)

- **HTTP code:** `200`
- **`leaflet` grep:** `3` matches (confirms the map tool page)
- **Reference key `matatu_wheel` grep:** `1` match
- **Leftover `__API_URL__` placeholder:** `0` matches (none — correctly injected)
- **Real execute-api URL injected:** FOUND
  - `const API = 'https://dh0959qwna.execute-api.us-east-1.amazonaws.com'`

(CloudFront briefly served a propagating body right after invalidation; retried a few
times with short sleeps, then the stable body confirmed all substrings above.)

```
HTTP code: 200
-- leaflet grep count: 3
-- matatu_wheel reference key grep count: 1
-- leftover __API_URL__ placeholder (expect none): 0
-- execute-api injected grep: execute-api.us-east-1.amazonaws.com
-- full injected API line: const API = 'https://dh0959qwna.execute-api.us-east-1.amazonaws.com'
```

## Check 3 — Backend /reports (confirms backend untouched & live)

- **HTTP code:** `200`
- **Reports array:** `11` items (non-empty)
- First report sample: `{"category_key":"evacuate","settlement":"Mathare","reference_object":"doorframe", ... "final_label":"Evacuate", "depth_m":"0.95", ...}`

```
GET https://dh0959qwna.execute-api.us-east-1.amazonaws.com/reports
HTTP code: 200
reports array count: 11
```

## API placeholder injection summary

**Was the `__API_URL__` placeholder correctly injected into BOTH index.html and app.html?** — **YES.**

Evidence:
- `index.html` (home, CloudFront root): `0` occurrences of `__API_URL__`; the real URL
  `https://dh0959qwna.execute-api.us-east-1.amazonaws.com` is present (`execute-api` grep hit;
  `const API = 'https://dh0959qwna.execute-api.us-east-1.amazonaws.com'`).
- `app.html` (tool page): `0` occurrences of `__API_URL__`; the same real URL is present
  (`execute-api` grep hit; identical `const API = '...'` injected line).

## Notes on deploy.sh fix (front-end verification logic only)

The deploy succeeded on the first run (CDK deployed, API URL injected into both pages,
DynamoDB seeded, all API checks passed). Its **step-9 verification logic** was stale from
before the redesign: it grepped the CloudFront **root** for `leaflet`, but after the redesign
the root is the new marketing home page (NO map/leaflet) and `leaflet` lives only on
`/app.html`. Fixed step 9 to:
- assert the **hero headline substring** on the root (the correct NEW-home-page proof), and
- assert **`leaflet`** on `/app.html` (where the map actually is).

No backend code, Lambda handler, engine, CDK resources, API routes, or payloads were changed.
Only `scripts/deploy.sh` front-end verification logic was adjusted. The injected `web/index.html`
and `web/app.html` reflect the deploy-time API URL rewrite.

**Result: ALL THREE LIVE CHECKS PASS. Kinga Maji front-end redesign is LIVE.**
