# Kinga Maji — the flood warning that shows its working

> **Category:** Social Good (Climate resilience) · **Lane:** Community
> **Live app:** <LIVE_CLOUDFRONT_URL> (no login)
> **Settlements:** Mathare and Mukuru, Nairobi
> _Built with a coding agent connected to AWS. Every depth it reports is computed by a deterministic engine, not guessed by a model._

## The problem, in one place

When the El Niño rains hit Nairobi, the water does not rise evenly. In Mathare and Mukuru — two of the city's largest informal settlements, built along rivers and on low ground — a lane that was ankle-deep at dawn can be waist-deep by the time a parent walks a child to school. The question a resident actually needs answered is not "will it rain" but "is *this* path safe to cross *right now*, and should I move things up or get out."

A weather app cannot answer that. It does not know how deep the water is on your lane.

## What Kinga Maji does

A resident photographs the standing water next to something of a known height that is already in the scene — a doorframe, a 20-litre jerrycan, a car tyre. Kinga Maji returns, in seconds:

- the water depth in metres,
- a category tied to a real consequence ("impassable for boda", "dangerous current", "evacuate"),
- and **the full arithmetic that produced the number**, so you can check it.

It then fuses that measurement with the next-24-hour rainfall forecast for that settlement and escalates the warning if more rain is coming over water that is already standing.

## The one thing that makes it different: it shows its working

Most "AI flood" tools ask a model to look at a photo and say how deep the water is. That is a guess, and you cannot check a guess.

Kinga Maji splits the job in two:

1. **The vision model (Amazon Bedrock, Nova) only reports pixels.** It locates the waterline and the top and bottom of the reference object. It is never asked for, and never outputs, a depth in metres.
2. **A deterministic Python engine computes the metres** from those pixels and the reference object's documented real-world height — and records every step.

A real trace from the live app reads:

```
- Reference object = doorframe, documented height H = 2.030 m
- Reference pixel span = bottom(600) - top(100) = 500 px
- Scale = 500 px / 2.030 m = 246.3 px per metre
- Submerged span = bottom(600) - waterline(365) = 235 px
- Depth = 235 px / 246.3 px/m = 0.95 m (47.0% of the reference submerged)
- Depth 0.95 m falls in [0.90, 99.00) m -> category 'evacuate'
- Forecast rainfall next 24h = 24.0 mm (Open-Meteo)
- Rule: >=20 mm forecast over >=0.10 m standing water -> escalate one notch
```

Every number on that page traces to a documented height, a measured pixel span, or a published rainfall figure. Nothing is asserted by a language model. You can recompute it by hand.

## How it is built on AWS

- **Amazon Bedrock (Nova, multimodal)** — reads the photo, returns pixel coordinates only.
- **AWS Lambda (Python)** — runs the deterministic depth engine, calls the public Open-Meteo rainfall API, writes the report.
- **Amazon DynamoDB** — stores each report (settlement, depth, category, trace, time).
- **Amazon API Gateway (HTTP API, no auth)** — the public endpoint.
- **Amazon S3 + CloudFront** — serve the always-up public risk map and upload page.
- **Amazon SNS** — the alert channel (SMS/WhatsApp fan-out).

The whole system is serverless and sits idle at near-zero cost between floods, which matters for a tool a community org would actually run.

## How the coding agent helped me ship

<AGENT_PROOF_AND_PROCESS — fill from deploy: the agent connected to AWS under the simi-ops profile,
scaffolded the CDK stack, wrote the Lambda + vision prompt, deployed live to CloudFront, and curl-verified
the public URL returned HTTP 200. Paste the deploy proof / caller-identity + cdk deploy output here.>

## Why this matters for Mathare and Mukuru

This is a Community-lane project: it is scoped to two specific settlements I can name, map, and point real reports at — not "flooding" in the abstract. The categories are written for how people there actually move (a boda stalling, a child's height, moving valuables up, evacuating a low-lying room), and the warnings go out over the channels people there actually use.

It does not replace official emergency services or county alerts. It gives a household one honest, checkable number about the water on their own lane, before they step into it.

## Try it

Open <LIVE_CLOUDFRONT_URL>, pick Mathare or Mukuru, choose a reference object, and upload a photo of standing water. You will get a depth, a category, and the arithmetic behind both.
