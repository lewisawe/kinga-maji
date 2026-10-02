# Kinga Maji — Implementation Plan (ship tonight)

Build & deploy a serverless AWS app to a LIVE public no-auth URL. Category: Social Good
(climate resilience), Community lane. Two settlements: Mathare (-1.2595, 36.8580),
Mukuru (-1.3167, 36.8667).

## Verified environment (do not re-investigate)

- Engine `engine/depth_engine.py` exists and self-check passes. REUSE AS-IS.
- `AWS_PROFILE=simi-ops`, account **888577033943**, region **us-east-1**, NO default
  region in profile — MUST set `AWS_DEFAULT_REGION=us-east-1` for every aws/cdk command
  and pin `env=Environment(account="888577033943", region="us-east-1")` in the CDK stack.
- CDK v2.1033 installed. `CDKToolkit` = CREATE_COMPLETE in us-east-1. Node 22, Python 3.14.
- `aws-cdk-lib` NOT installed in Python → create a venv and `pip install aws-cdk-lib constructs`.
- Bedrock: `amazon.nova-lite-v1:0` and `amazon.nova-pro-v1:0` BOTH confirmed invocable via
  the **Converse API** with image bytes on this account. Use `nova-lite` for the vision step.
- Open-Meteo (no key) confirmed: `hourly=precipitation&forecast_days=1`.
- Lambda needs ONLY boto3 (runtime-provided) + stdlib `urllib`/`json`/`base64`. No pip deps,
  **no Docker bundling** — vendor the engine into the asset dir and use `Code.from_asset`.
  Lambda runtime: `PYTHON_3_13` (newest supported; handler is version-agnostic).

## Locked engine contract (exact names)

- `REFERENCE_HEIGHTS_M` keys: `doorframe`, `jerrycan_20l`, `car_tyre`, `brick_course`, `matatu_wheel`.
- `DepthInput(reference_object, reference_top_px, reference_bottom_px, waterline_px)`.
- `compute_depth(DepthInput) -> DepthResult`; fields: `depth_m, reference_object,
  reference_height_m, submerged_fraction, category_key, category_label, consequence,
  trace (list[str]), ok (bool), error (str|None)`; has `.to_dict()`.
- `fuse_rainfall(DepthResult, rainfall_mm_next_24h: float) -> RiskResult`; fields:
  `base_category, rainfall_mm_next_24h, escalated (bool), final_label, advice, trace`.
- **The LLM returns ONLY pixel coords + reference object name. It NEVER outputs a depth.**

## File list to create

```
kinga-maji/
├── lambda/
│   ├── handler.py            # API Gateway HTTP API proxy handler (analyze, reports, seed)
│   └── depth_engine.py       # COPY of engine/depth_engine.py, vendored at deploy time
├── cdk/
│   ├── app.py                # cdk app entrypoint, pins account/region
│   ├── kinga_stack.py        # the stack
│   ├── cdk.json              # app = "python app.py"
│   └── requirements.txt      # aws-cdk-lib, constructs
├── web/
│   └── index.html            # single-file mobile-first page (Leaflet via CDN, inline JS/CSS)
└── scripts/
    └── deploy.sh             # vendor engine, cdk deploy, inject API URL into web, upload, curl-verify
```

## Lambda handler (`lambda/handler.py`)

Single handler for an HTTP API with payload format 2.0. Route on
`event["requestContext"]["http"]["method"]` + `event["rawPath"]`.

Routes:
- `POST /analyze` — body JSON: `{settlement, reference_object, image_base64}`
  (image_base64 optional; if absent OR `demo:true`, run demo path with canned pixel coords).
  1. Validate `settlement in {Mathare, Mukuru}`, `reference_object in REFERENCE_HEIGHTS_M`.
  2. Vision: `bedrock-runtime.converse(modelId="amazon.nova-lite-v1:0", ...)` with the
     image and the STRICT prompt (below). Parse the returned JSON for the 4 numbers.
     On parse failure, return 422 with the raw model text in the trace (never fabricate depth).
  3. `compute_depth(DepthInput(...))`. If `not result.ok` → return 400 with `result.error`.
  4. Fetch Open-Meteo for the settlement lat/lon (URL below), sum next-24h precipitation
     → `rainfall_mm`. On network error, default `rainfall_mm=0.0` and note it in trace.
  5. `fuse_rainfall(result, rainfall_mm)`.
  6. Write DynamoDB item (schema below). Publish SNS alert (best-effort; log, do not fail).
  7. Return `{ok, settlement, depth_m, reference_object, category_key, final_label, advice,
     escalated, rainfall_mm, lat, lon, trace: depth.trace + rainfall.trace, timestamp}`.
- `GET /reports` — query DynamoDB (scan, limit ~50, newest first), return
  `{reports: [...]}`. If table empty, return the in-code SAMPLE_REPORTS so the map is
  never empty. Each report has: settlement, timestamp, depth_m, category_key, final_label,
  advice, lat, lon.
- `POST /seed` — writes the 2-3 SAMPLE_REPORTS to DynamoDB (idempotent-ish; one per
  settlement). Called once post-deploy so persisted data exists for judges.
- `GET /health` — `{ok:true}`.
- CORS: handler returns `Access-Control-Allow-Origin: *` on all responses; also handle
  `OPTIONS` → 204. (API GW CORS is also configured; belt and suspenders.)

Env vars read by handler: `TABLE_NAME`, `SNS_TOPIC_ARN`, `MODEL_ID` (default
`amazon.nova-lite-v1:0`). Lat/lon table hardcoded in handler:
`{"Mathare": (-1.2595, 36.8580), "Mukuru": (-1.3167, 36.8667)}`.

### Bedrock Nova invoke shape (Converse API)

```python
resp = bedrock.converse(
    modelId=MODEL_ID,                       # amazon.nova-lite-v1:0
    messages=[{"role":"user","content":[
        {"image":{"format": fmt, "source":{"bytes": raw_bytes}}},  # fmt: "png" or "jpeg"
        {"text": VISION_PROMPT.format(reference_object=reference_object)},
    ]}],
    inferenceConfig={"maxTokens": 300, "temperature": 0.0},
)
text = resp["output"]["message"]["content"][0]["text"]
# extract first {...} JSON block from text, json.loads it
```

### STRICT pixel-only prompt (VISION_PROMPT)

```
You are a measurement tool, not an estimator. The image shows standing floodwater next
to a reference object: a {reference_object}. Image y-pixels increase DOWNWARD (top=0).

Return ONLY a single JSON object, no prose, no markdown fences, with EXACTLY these keys:
{{"reference_object": "{reference_object}",
  "reference_top_px": <number>,      // y-pixel of the TOP of the {reference_object}
  "reference_bottom_px": <number>,   // y-pixel of its BOTTOM / ground contact
  "waterline_px": <number>}}         // y-pixel where the water meets the {reference_object}

Rules:
- Output pixel coordinates ONLY. Do NOT output any depth, height in metres, or units.
- reference_bottom_px must be greater than reference_top_px.
- If you cannot see the object or waterline, set that value to null.
Return the JSON and nothing else.
```

Handler ignores any `reference_object` the model echoes that differs from the user's choice
(user's choice is authoritative for `REFERENCE_HEIGHTS_M` lookup).

### Open-Meteo request (per settlement)

```
https://api.open-meteo.com/v1/forecast?latitude={lat}&longitude={lon}
  &hourly=precipitation&forecast_days=1&timezone=Africa%2FNairobi
```
Parse `json["hourly"]["precipitation"]` (list of mm), `rainfall_mm = sum(...)`. Fetch via
`urllib.request.urlopen(url, timeout=5)`.

### DynamoDB item schema

Table `reports`, partition key `settlement` (S), sort key `timestamp` (S, ISO-8601 UTC).
Item: `settlement, timestamp, depth_m (N as Decimal/str), category_key, final_label,
advice, escalated (BOOL), rainfall_mm, lat, lon, reference_object`. Store floats as strings
or Decimal to satisfy DynamoDB (handler uses `json.dumps(..., default=str)` on read).

### SAMPLE_REPORTS (seed; in handler constant)

Two to three canned reports, one per settlement, with realistic categories so the map shows
color on first load, e.g. Mathare `dangerous`/`Dangerous current`, Mukuru
`impassable_boda`. Timestamps = recent ISO strings.

## CDK stack (`cdk/kinga_stack.py` + `app.py`)

`app.py`:
```python
app = App()
KingaStack(app, "KingaMajiStack", env=Environment(account="888577033943", region="us-east-1"))
app.synth()
```

Stack resources:
- `dynamodb.Table` `reports`: PK `settlement` (STRING), SK `timestamp` (STRING),
  billing PAY_PER_REQUEST, removalPolicy DESTROY.
- `sns.Topic` `kinga-alerts`.
- `lambda_.Function` `analyze`: runtime `PYTHON_3_13`, handler `handler.handler`,
  `code=Code.from_asset("../lambda")` (engine vendored there by deploy.sh BEFORE synth),
  timeout 30s, memory 512MB, env `{TABLE_NAME, SNS_TOPIC_ARN, MODEL_ID}`.
- IAM grants on the Lambda role:
  - `table.grant_read_write_data(fn)`
  - `topic.grant_publish(fn)`
  - explicit `iam.PolicyStatement(actions=["bedrock:InvokeModel"],
    resources=["arn:aws:bedrock:us-east-1::foundation-model/amazon.nova-lite-v1:0",
               "arn:aws:bedrock:us-east-1::foundation-model/amazon.nova-pro-v1:0"])`.
- `apigwv2.HttpApi` `kinga-api`: CORS `allow_origins=["*"]`, all methods, `allow_headers=["*"]`.
  Routes: `POST /analyze`, `GET /reports`, `POST /seed`, `GET /health` → `HttpLambdaIntegration`.
- `s3.Bucket` `web` (private; OAI/OAC), + `cloudfront.Distribution` with S3 origin,
  default root object `index.html`, viewer protocol redirect-to-https.
- `s3deploy.BucketDeployment` uploading `../web` to the bucket (CloudFront invalidation
  handled by BucketDeployment). NOTE: web/index.html needs the API URL — see deploy flow.
- `CfnOutput`: `CloudFrontURL` (`https://<dist>.cloudfront.net`), `ApiUrl`
  (`httpApi.apiEndpoint`), `TableName`, `TopicArn`.

Use `aws-cdk-lib` v2 import names: `aws_apigatewayv2` + `aws_apigatewayv2_integrations`
(`HttpLambdaIntegration`), `aws_s3_deployment` (`BucketDeployment`, `Source.asset`).

## Static front-end (`web/index.html`)

Single self-contained file (inline CSS + JS; Leaflet from CDN
`unpkg.com/leaflet@1.9.4`). Mobile-first.
- Header: "Kinga Maji — guard the water". One-line explainer.
- Leaflet map centered on Nairobi (`[-1.2864, 36.8172]`, zoom 12) with a marker per
  settlement; marker color = latest risk category from `/reports` (green nuisance →
  red evacuate). Popup shows settlement, final_label, advice, depth_m.
- Upload panel: `<select>` settlement (Mathare/Mukuru), `<select>` reference object
  (the 5 keys with friendly labels), `<input type=file accept="image/*" capture="environment">`,
  a "Analyze" button, and a "Run demo (no photo)" button that POSTs `{demo:true}`.
  On result: show depth_m + category + advice, and render the FULL trace array as a
  numbered `<ol>` (this is the scored, checkable part — make it prominent).
- Alerts panel: list latest `/reports` (settlement, label, advice, time).
- API base URL: a `const API = "__API_URL__"` placeholder that deploy.sh rewrites to the
  real `ApiUrl` output before the BucketDeployment upload. Must render fine cold (no auth,
  no blocking fetch failure — wrap fetches in try/catch and fall back to sample copy).

## Deploy + verification (`scripts/deploy.sh`)

All commands run with `AWS_PROFILE=simi-ops AWS_DEFAULT_REGION=us-east-1`.
1. `cp engine/depth_engine.py lambda/depth_engine.py` (vendor).
2. In `cdk/`: create venv, `pip install -r requirements.txt`.
3. `cdk deploy KingaMajiStack --require-approval never --outputs-file outputs.json`.
   (First synth uses `web/index.html` with the placeholder — acceptable; step 5 re-uploads.)
4. Read `ApiUrl` + `CloudFrontURL` from outputs.json.
5. `sed` the real `ApiUrl` into `web/index.html` (replace `__API_URL__`), then re-run
   `cdk deploy` (BucketDeployment re-uploads + invalidates), OR do a direct
   `aws s3 cp web/index.html s3://<bucket>/ && aws cloudfront create-invalidation`.
   Prefer the second (faster) for the final asset push.
6. `curl -s -o /dev/null -w "%{http_code}" <ApiUrl>/health` → expect 200.
7. `curl -s -X POST <ApiUrl>/seed` (populate DynamoDB), then
   `curl -s <ApiUrl>/reports` → expect JSON with reports (200).
8. `curl -s -X POST <ApiUrl>/analyze -d '{"demo":true,"settlement":"Mathare","reference_object":"doorframe"}'`
   → expect 200 with depth_m + trace (proves the full photo-to-depth path minus a real photo).
9. `curl -s -o /dev/null -w "%{http_code}" <CloudFrontURL>` → expect 200, and
   `curl -s <CloudFrontURL> | grep -i leaflet` → confirms map HTML served, no auth.
10. Print the live CloudFront URL + API URL as the final deliverable.

## Must-have vs nice-to-have

Must-have (ship gate): live CloudFront URL serving the populated map, `/reports` live,
`/analyze` demo path returning a real deterministic trace. SNS = best-effort publish+log
(documented demo, never blocks a request). Real photo upload works but demo mode guarantees
judges always see a result.
