"""
Kinga Maji — API Gateway HTTP API (payload v2.0) Lambda handler.

Full photo-to-depth path:
  1. Bedrock Nova vision returns ONLY pixel coordinates (never a depth in metres).
  2. The reused deterministic engine (depth_engine.py, vendored beside this file)
     computes every metre and emits a checkable trace.
  3. Open-Meteo forecast rainfall is fused for a deterministic risk escalation.
  4. The result is persisted to DynamoDB and (best-effort) pushed to SNS.

Routes: POST /analyze, GET /reports, POST /seed, GET /health.

All boto3 clients are created lazily inside functions so this module imports
cleanly without AWS credentials (enables a local smoke test).
"""

from __future__ import annotations

import base64
import json
import os
import re
import urllib.request
from datetime import datetime, timezone
from decimal import Decimal

# The engine is vendored next to this handler at deploy time (cp engine/depth_engine.py
# lambda/depth_engine.py). Import by the exact locked names — never recompute a depth here.
from depth_engine import (
    REFERENCE_HEIGHTS_M,
    DepthInput,
    compute_depth,
    fuse_rainfall,
)

# --- Constants ---------------------------------------------------------------

SETTLEMENTS: dict[str, tuple[float, float]] = {
    "Mathare": (-1.2595, 36.8580),
    "Mukuru": (-1.3167, 36.8667),
}

MODEL_ID = os.environ.get("MODEL_ID", "amazon.nova-lite-v1:0")
TABLE_NAME = os.environ.get("TABLE_NAME", "reports")
SNS_TOPIC_ARN = os.environ.get("SNS_TOPIC_ARN", "")

# Strict pixel-only prompt. The model returns ONLY pixel coordinates + the reference
# object name; it NEVER outputs a depth or any unit in metres. The engine does the maths.
VISION_PROMPT = """You are a measurement tool, not an estimator. The image shows standing floodwater next
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
Return the JSON and nothing else."""

# Canned pixel coords for the demo path (no photo). Chosen so the doorframe demo yields
# a real deterministic depth and a full trace. 500 px span / 2.03 m, 235 px submerged.
DEMO_COORDS = {
    "reference_top_px": 100.0,
    "reference_bottom_px": 600.0,
    "waterline_px": 365.0,
}

# Seed data so the map is never empty on first load. Differing categories give the
# markers distinct colours.
_NOW = datetime.now(timezone.utc)
SAMPLE_REPORTS: list[dict] = [
    {
        "settlement": "Mathare",
        "timestamp": _NOW.isoformat(),
        "depth_m": 0.72,
        "category_key": "dangerous",
        "final_label": "Dangerous current",
        "advice": "Adults can be swept. Do not cross. Move valuables up.",
        "lat": SETTLEMENTS["Mathare"][0],
        "lon": SETTLEMENTS["Mathare"][1],
        "reference_object": "doorframe",
    },
    {
        "settlement": "Mukuru",
        "timestamp": _NOW.isoformat(),
        "depth_m": 0.38,
        "category_key": "impassable_boda",
        "final_label": "Impassable for boda",
        "advice": "Motorcycles stall/stall-risk. Avoid crossing.",
        "lat": SETTLEMENTS["Mukuru"][0],
        "lon": SETTLEMENTS["Mukuru"][1],
        "reference_object": "matatu_wheel",
    },
]

# --- Lazy boto3 clients ------------------------------------------------------


def _bedrock():
    import boto3

    return boto3.client("bedrock-runtime")


def _table():
    import boto3

    return boto3.resource("dynamodb").Table(TABLE_NAME)


def _sns():
    import boto3

    return boto3.client("sns")


# --- Response helper ---------------------------------------------------------


def _resp(status: int, body) -> dict:
    """Build an HTTP API v2.0 proxy response with open CORS on every reply."""
    return {
        "statusCode": status,
        "headers": {
            "Content-Type": "application/json",
            "Access-Control-Allow-Origin": "*",
            "Access-Control-Allow-Headers": "*",
            "Access-Control-Allow-Methods": "*",
        },
        "body": json.dumps(body, default=str),
    }


# --- Vision ------------------------------------------------------------------


def vision(image_bytes: bytes, fmt: str, reference_object: str) -> tuple[float, float, float]:
    """
    Call Bedrock Nova via the Converse API and parse ONLY pixel coordinates.

    Returns (reference_top_px, reference_bottom_px, waterline_px). Raises ValueError
    (never fabricates numbers) when the model output is null/unparseable so the caller
    can return 422 with the raw text in the trace.
    """
    resp = _bedrock().converse(
        modelId=MODEL_ID,
        messages=[
            {
                "role": "user",
                "content": [
                    {"image": {"format": fmt, "source": {"bytes": image_bytes}}},
                    {"text": VISION_PROMPT.format(reference_object=reference_object)},
                ],
            }
        ],
        inferenceConfig={"maxTokens": 300, "temperature": 0.0},
    )
    text = resp["output"]["message"]["content"][0]["text"]

    match = re.search(r"\{.*\}", text, re.DOTALL)
    if not match:
        raise ValueError(f"No JSON object found in model output: {text!r}")
    try:
        data = json.loads(match.group(0))
    except json.JSONDecodeError as exc:
        raise ValueError(f"Unparseable model JSON: {text!r} ({exc})")

    try:
        top = data["reference_top_px"]
        bottom = data["reference_bottom_px"]
        waterline = data["waterline_px"]
    except (KeyError, TypeError):
        raise ValueError(f"Model JSON missing required pixel keys: {data!r}")

    if top is None or bottom is None or waterline is None:
        raise ValueError(
            f"Model returned null pixel value(s); object or waterline not visible: {data!r}"
        )

    try:
        return float(top), float(bottom), float(waterline)
    except (TypeError, ValueError):
        raise ValueError(f"Non-numeric pixel value(s) in model JSON: {data!r}")


# --- Rainfall ----------------------------------------------------------------


def rainfall(lat: float, lon: float) -> tuple[float, bool]:
    """
    Sum the next-24h forecast precipitation (mm) from Open-Meteo (no key).

    Returns (rainfall_mm, ok). On any failure returns (0.0, False) so the caller can
    add a trace note; it never raises.
    """
    url = (
        "https://api.open-meteo.com/v1/forecast"
        f"?latitude={lat}&longitude={lon}"
        "&hourly=precipitation&forecast_days=1&timezone=Africa%2FNairobi"
    )
    try:
        with urllib.request.urlopen(url, timeout=5) as r:
            data = json.loads(r.read().decode("utf-8"))
        precip = data["hourly"]["precipitation"]
        total = float(sum(p for p in precip if p is not None))
        return round(total, 1), True
    except Exception:
        return 0.0, False


# --- Persistence -------------------------------------------------------------


def _persist(item: dict) -> None:
    """Write a report item to DynamoDB (floats as Decimal via json round-trip)."""
    ddb_item = json.loads(json.dumps(item), parse_float=Decimal)
    _table().put_item(Item=ddb_item)


def _publish(final_label: str, advice: str, settlement: str) -> None:
    """Best-effort SNS publish; logs and swallows every error, never fails a request."""
    if not SNS_TOPIC_ARN:
        return
    try:
        _sns().publish(
            TopicArn=SNS_TOPIC_ARN,
            Subject=f"Kinga Maji alert: {settlement}",
            Message=f"{settlement}: {final_label}. {advice}",
        )
    except Exception as exc:  # pragma: no cover - best effort only
        print(f"[warn] SNS publish failed: {exc}")


# --- Routes ------------------------------------------------------------------


def _analyze(event: dict) -> dict:
    try:
        body = json.loads(event.get("body") or "{}")
    except json.JSONDecodeError:
        return _resp(400, {"ok": False, "error": "Request body is not valid JSON."})

    settlement = body.get("settlement")
    reference_object = body.get("reference_object")

    if settlement not in SETTLEMENTS:
        return _resp(
            400,
            {"ok": False, "error": f"Unknown settlement. Known: {sorted(SETTLEMENTS)}"},
        )
    if reference_object not in REFERENCE_HEIGHTS_M:
        return _resp(
            400,
            {
                "ok": False,
                "error": f"Unknown reference_object. Known: {sorted(REFERENCE_HEIGHTS_M)}",
            },
        )

    lat, lon = SETTLEMENTS[settlement]
    demo = bool(body.get("demo")) or not body.get("image_base64")

    if demo:
        top = DEMO_COORDS["reference_top_px"]
        bottom = DEMO_COORDS["reference_bottom_px"]
        waterline = DEMO_COORDS["waterline_px"]
    else:
        try:
            raw = base64.b64decode(body["image_base64"])
        except Exception:
            return _resp(400, {"ok": False, "error": "image_base64 is not valid base64."})
        fmt = "png" if raw[:8] == b"\x89PNG\r\n\x1a\n" else "jpeg"
        try:
            top, bottom, waterline = vision(raw, fmt, reference_object)
        except ValueError as exc:
            return _resp(
                422,
                {
                    "ok": False,
                    "error": "Vision step could not read pixel coordinates.",
                    "trace": [str(exc)],
                },
            )

    result = compute_depth(
        DepthInput(
            reference_object=reference_object,
            reference_top_px=top,
            reference_bottom_px=bottom,
            waterline_px=waterline,
        )
    )
    if not result.ok:
        return _resp(400, {"ok": False, "error": result.error, "trace": result.trace})

    rainfall_mm, rain_ok = rainfall(lat, lon)
    risk = fuse_rainfall(result, rainfall_mm)

    trace = list(result.trace) + list(risk.trace)
    if not rain_ok:
        trace.append("Open-Meteo unavailable; defaulted rainfall to 0.0 mm (no escalation).")

    timestamp = datetime.now(timezone.utc).isoformat()
    item = {
        "settlement": settlement,
        "timestamp": timestamp,
        "depth_m": result.depth_m,
        "category_key": result.category_key,
        "final_label": risk.final_label,
        "advice": risk.advice,
        "escalated": risk.escalated,
        "rainfall_mm": rainfall_mm,
        "lat": lat,
        "lon": lon,
        "reference_object": reference_object,
    }
    try:
        _persist(item)
    except Exception as exc:  # persistence must not block the deterministic result
        print(f"[warn] DynamoDB write failed: {exc}")
        trace.append(f"Persistence skipped: {exc}")

    _publish(risk.final_label, risk.advice, settlement)

    return _resp(
        200,
        {
            "ok": True,
            "settlement": settlement,
            "depth_m": result.depth_m,
            "reference_object": reference_object,
            "category_key": result.category_key,
            "final_label": risk.final_label,
            "advice": risk.advice,
            "escalated": risk.escalated,
            "rainfall_mm": rainfall_mm,
            "lat": lat,
            "lon": lon,
            "timestamp": timestamp,
            "trace": trace,
        },
    )


def _reports() -> dict:
    try:
        resp = _table().scan(Limit=50)
        items = resp.get("Items", [])
    except Exception as exc:
        print(f"[warn] DynamoDB scan failed: {exc}")
        items = []

    if not items:
        return _resp(200, {"reports": SAMPLE_REPORTS})

    items.sort(key=lambda r: r.get("timestamp", ""), reverse=True)
    return _resp(200, {"reports": items})


def _seed() -> dict:
    seeded = 0
    for item in SAMPLE_REPORTS:
        try:
            _persist(item)
            seeded += 1
        except Exception as exc:
            print(f"[warn] seed put failed: {exc}")
    return _resp(200, {"seeded": seeded})


# --- Entry point -------------------------------------------------------------


def handler(event: dict, context) -> dict:
    method = event.get("requestContext", {}).get("http", {}).get("method", "GET")
    path = event.get("rawPath", "/")

    if method == "OPTIONS":
        return _resp(204, {})

    if path == "/health" and method == "GET":
        return _resp(200, {"ok": True})
    if path == "/analyze" and method == "POST":
        return _analyze(event)
    if path == "/reports" and method == "GET":
        return _reports()
    if path == "/seed" and method == "POST":
        return _seed()

    return _resp(404, {"ok": False, "error": f"No route for {method} {path}"})
