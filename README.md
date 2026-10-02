# Kinga Maji — the flood warning that shows its working

> _Kinga maji_ is Swahili for "guard the water."
> A flood-readiness tool for **Mathare** and **Mukuru**, two informal settlements in Nairobi, Kenya.

**Live app:** https://d3eujpe11u21wb.cloudfront.net
Built for the AWS **Zero to Shipped** hackathon · Category: **Social Good (climate resilience)** · Lane: **Community**

---

## What it does

When the El Niño rains hit Nairobi, the water does not rise evenly. On a lane in Mathare or Mukuru, ankle-deep at dawn can be waist-deep by the school run. A weather app can't answer the question that matters: **is _this_ path safe to cross right now?**

A resident photographs the standing water next to something of a known height already in the scene — a doorframe, a 20-litre jerrycan, a car tyre. Kinga Maji returns, in seconds:

- the water depth in **metres**,
- a category tied to a real consequence (`impassable for boda`, `dangerous current`, `evacuate`),
- and the **full arithmetic** that produced the number, so you can check it.

It fuses that measurement with the next-24h rainfall forecast for the settlement's coordinates and escalates the warning when more rain is coming over water that is already standing.

## The one idea: it shows its working

Most "AI flood" tools ask a model how deep the water is. That's a guess, and you can't check a guess.

Kinga Maji splits the job in two:

1. **The vision model (Amazon Bedrock, Nova) only reports pixels** — it locates the waterline and the top and bottom of the reference object. It is never asked for, and never outputs, a depth in metres.
2. **A deterministic Python engine computes the metres** from those pixels and the reference object's documented height — and records every step.

A real trace:

```
Reference object = doorframe, documented height H = 2.030 m
Reference pixel span = bottom(600) - top(100) = 500 px
Scale = 500 px / 2.030 m = 246.3 px per metre
Submerged span = bottom(600) - waterline(365) = 235 px
Depth = 235 px / 246.3 px/m = 0.95 m (47.0% of the reference submerged)
Depth 0.95 m falls in [0.90, 99.00) m -> category 'evacuate'
Forecast rainfall next 24h = 0.0 mm (Open-Meteo)
Rule: no escalation (threshold not met)
```

Every number traces to a documented height, a measured pixel span, or a published rainfall figure. Nothing is asserted by a language model. You can recompute it by hand.

## Three ways to use it

| Page | What it is |
|------|-----------|
| **Home** (`/`) | The story, a worked example (annotated diagram + real trace), live current risk, and the autonomous alert feed. |
| **Check the water** (`/app.html`) | The tool: pick a settlement + reference object, upload a photo, get depth + category + full trace, on a live risk map. |
| **2024 replay** (`/replay.html`) | A retrospective of the real April–May 2024 Nairobi El Niño floods using **real Open-Meteo archive rainfall**, showing what Kinga Maji would have warned, day by day. |

## The autonomous watcher

Beyond the on-demand tool, a scheduled **agent** (Amazon EventBridge, hourly) pulls real rainfall for each settlement, runs the same deterministic escalation, and when risk crosses a threshold it **dispatches a warning on its own** — recording the full message body, the inputs, and the trace to a visible alert log (`GET /alerts`). An agent that watches and warns, not an app that waits to be asked.

> Delivery note: production delivery is SMS/WhatsApp; this demo records and displays every dispatched alert on the app's own pages, with no third-party subscription required.

## Architecture

```
Static site (S3 + CloudFront, no auth)
   home · tool · 2024 replay · live map
        │
        ▼
 API Gateway (HTTP API, open CORS, no auth)
        │
        ▼
   AWS Lambda (Python)
     ├─ Amazon Bedrock (Nova)  — vision: waterline + reference pixels ONLY
     ├─ deterministic depth engine (pure Python, fully traced)
     ├─ Open-Meteo API          — real per-location rainfall (forecast + archive)
     └─ Amazon DynamoDB         — reports + autonomous alerts
        ▲
   Amazon EventBridge (hourly) — the autonomous watcher cycle
```

| Service | Role |
|---------|------|
| Amazon Bedrock (Nova) | Reads the photo, returns pixel coordinates only |
| AWS Lambda (Python) | Deterministic depth engine, rainfall fusion, routes |
| Amazon DynamoDB | Stores reports and dispatched alerts |
| Amazon API Gateway | Public no-auth HTTP API |
| Amazon S3 + CloudFront | Serves the always-up static site |
| Amazon EventBridge | Schedules the autonomous watcher |

Serverless end to end — near-zero idle cost between floods.

## Repository layout

```
engine/depth_engine.py   # the deterministic depth + rainfall-fusion engine (the scoring core)
lambda/handler.py        # Bedrock vision (pixels only) -> engine -> Open-Meteo -> DynamoDB; routes + watcher
cdk/                     # AWS CDK (Python) infrastructure
web/                     # static front-end: index.html, app.html, replay.html, kinga.css, kinga.js
scripts/deploy.sh        # idempotent deploy: cdk deploy, inject API URL, upload web, seed, verify live
```

## API

| Route | Method | Purpose |
|-------|--------|---------|
| `/analyze` | POST | Photo (or demo) → depth + category + full trace |
| `/reports` | GET | Recent measurements for the map |
| `/alerts` | GET | Alerts dispatched by the autonomous watcher |
| `/watch` | POST | Run one watcher cycle on demand |
| `/health` | GET | Health check |

## Run it yourself

Prerequisites: an AWS account with Amazon Bedrock (Nova) enabled in your region, AWS CLI configured, Node (for the CDK CLI) and Python 3.

```bash
# account + region are read from your environment (not hardcoded)
export CDK_DEPLOY_ACCOUNT="$(aws sts get-caller-identity --query Account --output text)"
export CDK_DEPLOY_REGION=us-east-1

bash scripts/deploy.sh
```

`deploy.sh` is idempotent: it vendors the engine into the Lambda bundle, runs `cdk deploy`, injects the live API URL into the web pages, uploads them to S3, invalidates CloudFront, seeds sample data, and curl-verifies every endpoint is live with no auth.

## The deterministic engine, standalone

The engine runs with no AWS and no network — the measurement is checkable in isolation:

```bash
python3 engine/depth_engine.py
```

## Honesty notes

- Rainfall is **real** Open-Meteo data for each settlement's coordinates; `0 mm` is shown truthfully on dry days.
- The 2024 replay uses real archive rainfall and is clearly labeled retrospective; it does not fabricate measured depths.
- Kinga Maji does not replace official emergency services or county alerts. It gives a household one honest, checkable number about the water on their own lane.

## License

MIT
