# Kinga Maji — the flood warning that shows its working

> **Category:** Social Good (Climate resilience) · **Lane:** Community
> **Live app:** https://d3eujpe11u21wb.cloudfront.net (no login)
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

I built Kinga Maji with a coding agent connected directly to my AWS account. The connection is real and documented: every AWS call in this project ran through the agent under a named IAM identity.

```
$ aws sts get-caller-identity
{
    "Account": "888577033943",
    "Arn": "arn:aws:iam::888577033943:user/simi-ops"
}
```

The agent did the work end to end:

1. **Verified the ground it was standing on** — confirmed the IAM identity, that Amazon Bedrock Nova (Lite and Pro) answered in this account and region, and that the public Open-Meteo rainfall API returned data with no key.
2. **Wrote the deterministic depth engine first** and ran its self-check before any cloud code existed — the engine is the part that must be trustworthy, so it was proven in isolation.
3. **Built the Lambda handler** with a strict vision prompt that returns pixel coordinates only, feeding the deterministic engine so the model never emits a depth.
4. **Authored the CDK stack** (DynamoDB, Lambda, HTTP API, S3 + CloudFront, SNS), with the environment pinned to account 888577033943 / us-east-1.
5. **Deployed it live** with `cdk deploy`, uploaded the web assets, invalidated CloudFront, seeded the map, and then curl-verified every endpoint returned HTTP 200 with no auth.

A verification step reproduced the whole chain before I called it shipped: the engine self-check, a live `/analyze` returning depth 0.95 m with a nine-step trace, a fresh `cdk synth`, and HTTP 200 from the public CloudFront URL. The stack reports `UPDATE_COMPLETE`.

**Live now:** the app at https://d3eujpe11u21wb.cloudfront.net and the API at https://dh0959qwna.execute-api.us-east-1.amazonaws.com — both reachable with no login.

## Why this matters for Mathare and Mukuru

This is a Community-lane project: it is scoped to two specific settlements I can name, map, and point real reports at — not "flooding" in the abstract. The categories are written for how people there actually move (a boda stalling, a child's height, moving valuables up, evacuating a low-lying room), and the warnings go out over the channels people there actually use.

It does not replace official emergency services or county alerts. It gives a household one honest, checkable number about the water on their own lane, before they step into it.

## Try it

Open https://d3eujpe11u21wb.cloudfront.net — the home page shows how it works and the current risk in both settlements. Then open **Check the water** (`/app.html`), pick Mathare or Mukuru, choose a reference object, and upload a photo of standing water. You will get a depth, a category, and the arithmetic behind both.
