#!/usr/bin/env bash
#
# Kinga Maji — live deploy + proof script (FEAT-004).
#
# Vendors the deterministic engine beside the Lambda handler, deploys the CDK
# stack under the simi-ops profile in us-east-1, injects the real API URL into
# the static front-end, seeds DynamoDB, then curl-proves the live, no-auth app.
#
# Idempotent / re-runnable: safe to run repeatedly (cdk deploy is a no-op when
# nothing changed; /seed is one item per settlement).
#
# Usage:  bash scripts/deploy.sh
#
set -euo pipefail

# --- Fixed environment (profile has NO default region: pin it) ---------------
export AWS_PROFILE=simi-ops
export AWS_DEFAULT_REGION=us-east-1
export AWS_REGION=us-east-1

# --- Resolve absolute paths (run from anywhere) ------------------------------
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
ENGINE="$ROOT/engine/depth_engine.py"
LAMBDA_DIR="$ROOT/lambda"
CDK_DIR="$ROOT/cdk"
WEB_INDEX="$ROOT/web/index.html"
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

# --- 5. Inject real API URL into web/index.html, re-upload + invalidate ------
echo "==> [5/9] Injecting API URL into web/index.html and re-deploying asset"
# Rewrite the placeholder in place (idempotent: replaces whatever is currently there).
python3 - "$WEB_INDEX" "$API_URL" <<'PY'
import re, sys
path, api = sys.argv[1], sys.argv[2]
with open(path, "r", encoding="utf-8") as f:
    html = f.read()
# Replace both the raw placeholder and any previously-injected endpoint value.
html = html.replace("__API_URL__", api)
html = re.sub(r"const API = '[^']*';", "const API = '%s';" % api, html, count=1)
with open(path, "w", encoding="utf-8") as f:
    f.write(html)
print("    wrote API =", api)
PY

# Re-run cdk deploy so the BucketDeployment re-uploads the API-injected index.html
# and invalidates CloudFront. This is the reliable path (asset hash changed).
"$CDK" deploy KingaMajiStack --require-approval never --outputs-file "$OUTPUTS"

# --- 6. Seed DynamoDB so /reports is populated for judges --------------------
echo "==> [6/9] Seeding DynamoDB (POST /seed)"
curl -s -X POST "$API_URL/seed" -H 'content-type: application/json' || true
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

echo "==> [8/9] Verifying /analyze demo path"
analyze_json="$(curl -s -X POST "$API_URL/analyze" -H 'content-type: application/json' \
  -d '{"demo":true,"settlement":"Mathare","reference_object":"doorframe"}')"
echo "$analyze_json" | python3 -c 'import sys,json; d=json.load(sys.stdin); assert "depth_m" in d and d.get("trace"), "missing depth_m/trace"; print("    analyze depth_m   =", d["depth_m"], "| trace steps =", len(d["trace"]))' || { echo "    FAIL /analyze demo"; echo "$analyze_json"; fail=1; }

echo "==> [9/9] Verifying CloudFront serves the API-injected map (no auth)"
# CloudFront can briefly serve an empty/propagating body right after an
# invalidation; retry a few times before judging the HTML checks.
cf_html=""
code=""
for attempt in 1 2 3 4 5; do
  code="$(curl -s -o /dev/null -w '%{http_code}' "$CF_URL")"
  cf_html="$(curl -s "$CF_URL")"
  if [ "$code" = "200" ] && echo "$cf_html" | grep -qi leaflet; then
    break
  fi
  echo "    (attempt $attempt: code=$code, retrying CloudFront in 5s)"
  sleep 5
done
echo "    CloudFront root    -> $code"
[ "$code" = "200" ] || { echo "    FAIL CloudFront root"; fail=1; }
echo "$cf_html" | grep -qi leaflet && echo "    leaflet present    -> yes" || { echo "    FAIL leaflet missing"; fail=1; }
if echo "$cf_html" | grep -q "$API_URL"; then
  echo "    injected API URL   -> yes"
else
  echo "    FAIL injected API URL missing (still placeholder?)"; fail=1
fi
if echo "$cf_html" | grep -q "__API_URL__"; then
  echo "    FAIL placeholder __API_URL__ still present"; fail=1
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
