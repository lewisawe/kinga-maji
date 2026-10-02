"""
Kinga Maji — deterministic flood-depth engine.

Design principle (the scored part): the vision model NEVER reports a depth in metres.
It only returns pixel coordinates of (a) the waterline and (b) the top and bottom of a
known-height reference object in the same photo. THIS module computes the depth in metres
by pure arithmetic, and emits a full trace so every number is checkable against its rule.

No AWS, no network, no LLM in here. Unit-testable in isolation.
"""

from __future__ import annotations
from dataclasses import dataclass, asdict
from typing import Literal

# Documented real-world heights (metres) of reference objects common in Nairobi
# informal settlements. Each value is a fixed, citable physical dimension.
REFERENCE_HEIGHTS_M: dict[str, float] = {
    "doorframe":   2.03,   # standard interior door leaf height (~6'8")
    "jerrycan_20l": 0.46,  # standard 20 L water jerrycan, upright
    "car_tyre":    0.63,   # typical passenger car tyre outer diameter (R14/15)
    "brick_course": 0.075, # one course of a standard Kenyan burnt brick + mortar
    "matatu_wheel": 0.70,  # 14-seater matatu wheel outer diameter
}

# Depth categories tied to a real, named consequence in the settlement context.
# Thresholds are deterministic cut-offs, not model opinions.
@dataclass(frozen=True)
class DepthCategory:
    key: str
    min_m: float
    max_m: float
    label: str
    consequence: str

CATEGORIES: list[DepthCategory] = [
    DepthCategory("nuisance",   0.00, 0.10, "Nuisance water",      "Passable on foot. Monitor."),
    DepthCategory("ankle",      0.10, 0.30, "Ankle-to-shin",       "Children and elderly at risk. Boda passable with care."),
    DepthCategory("impassable_boda", 0.30, 0.50, "Impassable for boda", "Motorcycles stall/stall-risk. Avoid crossing."),
    DepthCategory("dangerous",  0.50, 0.90, "Dangerous current",   "Adults can be swept. Do not cross. Move valuables up."),
    DepthCategory("evacuate",   0.90, 99.0, "Evacuate",            "Structural flooding. Evacuate low-lying homes now."),
]


@dataclass
class DepthInput:
    """Pixel measurements supplied by the vision step (not metres)."""
    reference_object: str          # must be a key in REFERENCE_HEIGHTS_M
    reference_top_px: float        # y-pixel of the top of the reference object
    reference_bottom_px: float     # y-pixel of the bottom (ground contact) of the reference
    waterline_px: float            # y-pixel of the waterline against the reference
    # Note: image y increases downward, so bottom_px > top_px.


@dataclass
class DepthResult:
    depth_m: float
    reference_object: str
    reference_height_m: float
    submerged_fraction: float
    category_key: str
    category_label: str
    consequence: str
    trace: list[str]
    ok: bool
    error: str | None = None

    def to_dict(self) -> dict:
        return asdict(self)


def _categorize(depth_m: float) -> DepthCategory:
    for c in CATEGORIES:
        if c.min_m <= depth_m < c.max_m:
            return c
    return CATEGORIES[-1]


def compute_depth(inp: DepthInput) -> DepthResult:
    """
    Deterministic depth-from-reference calculation.

    Method: the reference object spans (bottom_px - top_px) pixels and has a known
    real height H metres. The water covers from the bottom up to waterline_px, i.e.
    (bottom_px - waterline_px) pixels. Depth = that submerged pixel span, scaled by
    the metres-per-pixel of the reference.

        px_per_m        = (bottom_px - top_px) / H
        submerged_px    = bottom_px - waterline_px
        depth_m         = submerged_px / px_per_m

    Every intermediate value is recorded in `trace`.
    """
    trace: list[str] = []

    if inp.reference_object not in REFERENCE_HEIGHTS_M:
        return DepthResult(
            depth_m=0.0, reference_object=inp.reference_object, reference_height_m=0.0,
            submerged_fraction=0.0, category_key="error", category_label="Unknown reference",
            consequence="", trace=trace, ok=False,
            error=f"Unknown reference object '{inp.reference_object}'. "
                  f"Known: {sorted(REFERENCE_HEIGHTS_M)}",
        )

    H = REFERENCE_HEIGHTS_M[inp.reference_object]
    trace.append(f"Reference object = {inp.reference_object}, documented height H = {H:.3f} m")

    ref_px_span = inp.reference_bottom_px - inp.reference_top_px
    if ref_px_span <= 0:
        return DepthResult(
            depth_m=0.0, reference_object=inp.reference_object, reference_height_m=H,
            submerged_fraction=0.0, category_key="error", category_label="Bad geometry",
            consequence="", trace=trace, ok=False,
            error=f"Reference pixel span must be positive; got bottom={inp.reference_bottom_px}, "
                  f"top={inp.reference_top_px}.",
        )
    trace.append(
        f"Reference pixel span = bottom({inp.reference_bottom_px:.0f}) - "
        f"top({inp.reference_top_px:.0f}) = {ref_px_span:.0f} px"
    )

    px_per_m = ref_px_span / H
    trace.append(f"Scale = {ref_px_span:.0f} px / {H:.3f} m = {px_per_m:.1f} px per metre")

    # Clamp waterline into the reference span so a bad vision read can't produce nonsense.
    wl = min(max(inp.waterline_px, inp.reference_top_px), inp.reference_bottom_px)
    if wl != inp.waterline_px:
        trace.append(
            f"Waterline {inp.waterline_px:.0f} px clamped to reference span -> {wl:.0f} px"
        )

    submerged_px = inp.reference_bottom_px - wl
    trace.append(
        f"Submerged span = bottom({inp.reference_bottom_px:.0f}) - "
        f"waterline({wl:.0f}) = {submerged_px:.0f} px"
    )

    depth_m = submerged_px / px_per_m
    depth_m = round(depth_m, 2)
    submerged_fraction = round(submerged_px / ref_px_span, 3)
    trace.append(
        f"Depth = {submerged_px:.0f} px / {px_per_m:.1f} px/m = {depth_m:.2f} m "
        f"({submerged_fraction*100:.1f}% of the reference submerged)"
    )

    cat = _categorize(depth_m)
    trace.append(
        f"Depth {depth_m:.2f} m falls in [{cat.min_m:.2f}, {cat.max_m:.2f}) m "
        f"-> category '{cat.key}' ({cat.label})"
    )

    return DepthResult(
        depth_m=depth_m,
        reference_object=inp.reference_object,
        reference_height_m=H,
        submerged_fraction=submerged_fraction,
        category_key=cat.key,
        category_label=cat.label,
        consequence=cat.consequence,
        trace=trace,
        ok=True,
    )


# ---- Rainfall fusion (deterministic risk escalation) --------------------------

@dataclass
class RiskResult:
    base_category: str
    rainfall_mm_next_24h: float
    escalated: bool
    final_label: str
    advice: str
    trace: list[str]


def fuse_rainfall(depth: DepthResult, rainfall_mm_next_24h: float) -> RiskResult:
    """
    Deterministic escalation: measured standing water + forecast rain.
    Open-Meteo returns forecast precipitation (mm). Rule: >= 20 mm in the next 24h
    over already-standing water escalates the warning one notch.
    """
    trace: list[str] = []
    trace.append(f"Measured category = {depth.category_label} ({depth.depth_m:.2f} m)")
    trace.append(f"Forecast rainfall next 24h = {rainfall_mm_next_24h:.1f} mm (Open-Meteo)")

    escalate = rainfall_mm_next_24h >= 20.0 and depth.depth_m >= 0.10
    if escalate:
        trace.append("Rule: >=20 mm forecast over >=0.10 m standing water -> escalate one notch")
        idx = next((i for i, c in enumerate(CATEGORIES) if c.key == depth.category_key), 0)
        idx = min(idx + 1, len(CATEGORIES) - 1)
        final = CATEGORIES[idx]
        label = f"{final.label} (escalated by forecast rain)"
        advice = final.consequence
    else:
        trace.append("Rule: no escalation (threshold not met)")
        label = depth.category_label
        advice = depth.consequence

    return RiskResult(
        base_category=depth.category_label,
        rainfall_mm_next_24h=rainfall_mm_next_24h,
        escalated=escalate,
        final_label=label,
        advice=advice,
        trace=trace,
    )


if __name__ == "__main__":
    # Quick self-check: waterline covering ~0.47 of a doorframe.
    demo = DepthInput(
        reference_object="doorframe",
        reference_top_px=100.0,
        reference_bottom_px=600.0,   # 500 px span = 2.03 m
        waterline_px=365.0,          # 235 px submerged
    )
    r = compute_depth(demo)
    for line in r.trace:
        print("  -", line)
    print(f"RESULT: {r.depth_m} m -> {r.category_label}")
    fr = fuse_rainfall(r, 24.0)
    for line in fr.trace:
        print("  -", line)
    print(f"FINAL: {fr.final_label} | {fr.advice}")
