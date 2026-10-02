#!/usr/bin/env bash
#
# Kinga Maji — live deploy + proof script.
#
# Vendors the deterministic engine beside the Lambda handler, deploys the CDK
# stack with your configured AWS profile in us-east-1, injects the real API URL
# into the static front-end, seeds DynamoDB, then curl-proves the live, no-auth app.
#
# Idempotent / re-runnable: safe to run repeatedly (cdk deploy is a no-op when
# nothing changed; /seed is one item per settlement).
#
# Usage:  AWS_PROFILE=<your-profile> bash scripts/deploy.sh
#         (defaults to your current AWS credentials / default profile)
set -euo pipefail

# --- Environment: use the caller's AWS profile; pin a region (some profiles
#     have no default region) ------------------------------------------------
export AWS_PROFILE="${AWS_PROFILE:-default}"
export AWS_DEFAULT_REGION="${AWS_DEFAULT_REGION:-us-east-1}"
export AWS_REGION="$AWS_DEFAULT_REGION"

# Resolve the deploy account from the active profile so cdk/app.py stays
# account-agnostic (the repo is not hardwired to one AWS account).
export CDK_DEPLOY_ACCOUNT="$(aws sts get-caller-identity --query Account --output text)"
export CDK_DEPLOY_REGION="$AWS_DEFAULT_REGION"
echo "==> deploy account = $CDK_DEPLOY_ACCOUNT (resolved from profile $AWS_PROFILE)"

# --- Resolve absolute paths (run from anywhere) ------------------------------
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
ENGINE="$ROOT/engine/depth_engine.py"
LAMBDA_DIR="$ROOT/lambda"
CDK_DIR="$ROOT/cdk"
WEB_INDEX="$ROOT/web/index.html"
WEB_APP="$ROOT/web/app.html"
WEB_REPLAY="$ROOT/web/replay.html"
OUTPUTS="$CDK_DIR/outputs.json"

echo "==> Kinga Maji deploy  (profile=$AWS_PROFILE region=$AWS_DEFAULT_REGION)"
echo "==> root: $ROOT"

# --- 1. Vendor the engine beside the handler ---------------------------------
echo "==> [1/9] Vendoring engine -> lambda/depth_engine.py"
cp "$ENGINE" "$LAMBDA_DIR/depth_engine.py"

# --- 2. CDK venv + deps ------------------------------------------------------
echo "==> [2/9] CDK python venv + requirements"
cd "$CDK_DIR"
if [ ! -d .venv ]; then
  python3 -m venv .venv
fi
# shellcheck disable=SC1091
. .venv/bin/activate
pip install -q -r requirements.txt

# The globally installed CDK CLI (2.1033) is too old for aws-cdk-lib 2.272's
# cloud-assembly schema. A newer CLI is installed locally in cdk/node_modules.
if [ -x "$CDK_DIR/node_modules/.bin/cdk" ]; then
  CDK="$CDK_DIR/node_modules/.bin/cdk"
else
  echo "==> installing local aws-cdk CLI (schema compatibility)"
  npm install --no-save aws-cdk@latest >/dev/null 2>&1
  CDK="$CDK_DIR/node_modules/.bin/cdk"
fi
echo "==> using CDK CLI: $("$CDK" --version)"

# --- 3. Deploy (first pass: placeholder API URL is fine; step 5 re-uploads) --
echo "==> [3/9] cdk deploy KingaMajiStack"
"$CDK" deploy KingaMajiStack --require-approval never --outputs-file "$OUTPUTS"

# --- 4. Read stack outputs ---------------------------------------------------
echo "==> [4/9] Reading stack outputs"
API_URL="$(python3 -c "import json;print(json.load(open('$OUTPUTS'))['KingaMajiStack']['ApiUrl'])")"
CF_URL="$(python3 -c "import json;print(json.load(open('$OUTPUTS'))['KingaMajiStack']['CloudFrontURL'])")"
BUCKET="$(python3 -c "import json,sys;d=json.load(open('$OUTPUTS'))['KingaMajiStack'];print(d.get('WebBucketName',''))" 2>/dev/null || true)"
API_URL="${API_URL%/}"
echo "    ApiUrl        = $API_URL"
echo "    CloudFrontURL = $CF_URL"

# --- 5. Inject real API URL into web/*.html, re-upload + invalidate ----------
echo "==> [5/9] Injecting API URL into web/index.html + web/app.html + web/replay.html and re-deploying asset"
# Rewrite the placeholder in place for ALL pages (idempotent: replaces whatever
# is currently there). index.html + app.html share the __API_URL__ placeholder
# and the `const API = '...';` line; replay.html is archive-only and normally
# carries no placeholder, so both replacements are harmless no-ops there. The
# loop skips any path that does not exist.
python3 - "$API_URL" "$WEB_INDEX" "$WEB_APP" "$WEB_REPLAY" <<'PY'
import os, re, sys
api = sys.argv[1]
for path in sys.argv[2:]:
    if not os.path.isfile(path):
        print("    skip (missing) ->", path)
        continue
    with open(path, "r", encoding="utf-8") as f:
        html = f.read()
    # Replace both the raw placeholder and any previously-injected endpoint value.
    html = html.replace("__API_URL__", api)
    html = re.sub(r"const API = '[^']*';", "const API = '%s';" % api, html, count=1)
    with open(path, "w", encoding="utf-8") as f:
        f.write(html)
    print("    wrote API =", api, "->", path)
PY

# Re-run cdk deploy so the BucketDeployment re-uploads the API-injected
# index.html + app.html and invalidates CloudFront. This is the reliable path
# (asset hash changed).
"$CDK" deploy KingaMajiStack --require-approval never --outputs-file "$OUTPUTS"

# --- 6. Seed DynamoDB so /reports is populated for judges --------------------
echo "==> [6/9] Seeding DynamoDB (POST /seed)"
curl -s -X POST "$API_URL/seed" -H 'content-type: application/json' || true
echo

# --- 6b. Seed ONE real autonomous alert via a real watcher cycle -------------
# The watcher reads REAL Open-Meteo forecast rainfall and the just-seeded report
# depths (Mathare 0.72 m = 'dangerous', Mukuru 0.38 m = 'impassable_boda').
# Mathare's seeded depth is already in DANGER_KEYS, so POST /watch dispatches at
# least one alert regardless of today's forecast — making /alerts deterministically
# non-empty given the seed. A short settle lets the seed propagate before /watch
# reads it; do NOT fabricate an alert if it is empty (see verify step).
echo "==> [6b] Seeding one real autonomous alert (POST /watch)"
sleep 3
curl -s -X POST "$API_URL/watch" -H 'content-type: application/json' || true
echo

# --- 7-9. PROVE LIVE ---------------------------------------------------------
echo "==> [7/9] Verifying live endpoints (no auth)"
fail=0

code="$(curl -s -o /dev/null -w '%{http_code}' "$API_URL/health")"
echo "    /health            -> $code"
[ "$code" = "200" ] || { echo "    FAIL /health"; fail=1; }

reports_json="$(curl -s "$API_URL/reports")"
code="$(curl -s -o /dev/null -w '%{http_code}' "$API_URL/reports")"
echo "    /reports           -> $code"
echo "$reports_json" | python3 -c 'import sys,json; d=json.load(sys.stdin); assert d.get("reports"), "empty reports"; print("    reports count     =", len(d["reports"]))' || { echo "    FAIL /reports (empty or bad JSON)"; fail=1; }

alerts_json="$(curl -s "$API_URL/alerts")"
code="$(curl -s -o /dev/null -w '%{http_code}' "$API_URL/alerts")"
echo "    /alerts            -> $code"
echo "$alerts_json" | python3 -c 'import sys,json; d=json.load(sys.stdin); assert d.get("alerts"), "empty alerts"; print("    alerts count      =", len(d["alerts"]))' || { echo "    FAIL /alerts (empty or bad JSON)"; fail=1; }

echo "==> [8/9] Verifying /analyze demo path"
analyze_json="$(curl -s -X POST "$API_URL/analyze" -H 'content-type: application/json' \
  -d '{"demo":true,"settlement":"Mathare","reference_object":"doorframe"}')"
echo "$analyze_json" | python3 -c 'import sys,json; d=json.load(sys.stdin); assert "depth_m" in d and d.get("trace"), "missing depth_m/trace"; print("    analyze depth_m   =", d["depth_m"], "| trace steps =", len(d["trace"]))' || { echo "    FAIL /analyze demo"; echo "$analyze_json"; fail=1; }

echo "==> [9/9] Verifying CloudFront serves the API-injected pages (no auth)"
# CloudFront can briefly serve an empty/propagating body right after an
# invalidation; retry a few times before judging the HTML checks.
# The root is the redesigned home page (hero headline, NO map/leaflet); the
# interactive map/leaflet lives on /app.html, which is checked separately below.
HERO_SUBSTR="the flood warning that shows its working"
cf_html=""
app_html=""
code=""
app_code=""
for attempt in 1 2 3 4 5 6; do
  code="$(curl -s -o /dev/null -w '%{http_code}' "$CF_URL")"
  cf_html="$(curl -s "$CF_URL")"
  app_code="$(curl -s -o /dev/null -w '%{http_code}' "$CF_URL/app.html")"
  app_html="$(curl -s "$CF_URL/app.html")"
  if [ "$code" = "200" ] && [ "$app_code" = "200" ] \
     && echo "$cf_html" | grep -qi "$HERO_SUBSTR" \
     && echo "$app_html" | grep -qi leaflet; then
    break
  fi
  echo "    (attempt $attempt: root=$code app=$app_code, waiting 5s for CloudFront propagation)"
  sleep 5
done
echo "    CloudFront root    -> $code"
[ "$code" = "200" ] || { echo "    FAIL CloudFront root"; fail=1; }
echo "$cf_html" | grep -qi "$HERO_SUBSTR" && echo "    home hero present  -> yes" || { echo "    FAIL home hero headline missing"; fail=1; }
if echo "$cf_html" | grep -q "$API_URL"; then
  echo "    injected API URL   -> yes"
else
  echo "    FAIL injected API URL missing (still placeholder?)"; fail=1
fi
if echo "$cf_html" | grep -q "__API_URL__"; then
  echo "    FAIL placeholder __API_URL__ still present"; fail=1
fi

# The restyled tool page was fetched inside the retry loop above.
echo "    CloudFront /app.html -> $app_code"
[ "$app_code" = "200" ] || { echo "    FAIL CloudFront /app.html"; fail=1; }
echo "$app_html" | grep -qi leaflet && echo "    app.html leaflet   -> yes" || { echo "    FAIL app.html leaflet missing"; fail=1; }
if echo "$app_html" | grep -q "$API_URL"; then
  echo "    app.html injected API URL -> yes"
else
  echo "    FAIL app.html injected API URL missing (still placeholder?)"; fail=1
fi
if echo "$app_html" | grep -q "__API_URL__"; then
  echo "    FAIL app.html placeholder __API_URL__ still present"; fail=1
fi

# Verify the 2024 replay page is served with its real-data citation present.
replay_code="$(curl -s -o /dev/null -w '%{http_code}' "$CF_URL/replay.html")"
replay_html="$(curl -s "$CF_URL/replay.html")"
echo "    CloudFront /replay.html -> $replay_code"
[ "$replay_code" = "200" ] || { echo "    FAIL CloudFront /replay.html"; fail=1; }
echo "$replay_html" | grep -qi "archive-api.open-meteo.com" && echo "    replay citation    -> yes" || { echo "    FAIL replay.html citation missing"; fail=1; }
if echo "$replay_html" | grep -q "__API_URL__"; then
  echo "    FAIL replay.html placeholder __API_URL__ present (should be archive-only)"; fail=1
fi

echo
if [ "$fail" -ne 0 ]; then
  echo "########################################################"
  echo "# SHIP GATE FAILED — see FAIL lines above."
  echo "########################################################"
  exit 1
fi

echo "########################################################"
echo "# KINGA MAJI IS LIVE"
echo "#   CloudFront : $CF_URL"
echo "#   API        : $API_URL"
echo "########################################################"
