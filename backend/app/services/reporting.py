from __future__ import annotations

from typing import Optional


def _resolve_pack(domain: str | None):
    from app.core.domain_registry import resolve
    from domain_packs.bootstrap import bootstrap

    bootstrap()
    return resolve(domain)

# Confidence level thresholds per docs/Architecture.md:
#   L1 Primary Data:      0.95 – 0.99
#   L2 Supplier Data:     0.80 – 0.95
#   L3 Trade Data:        0.70 – 0.85
#   L4 Industry Average:  0.50 – 0.75
#   L5 Fallback Logic:    0.25 – 0.50
# Overlaps (e.g. 0.95) resolve to the higher level.

_CONFIDENCE_BANDS: list[tuple[float, float, str, str]] = [
    (0.95, 1.00, "Level 1 - Primary Data",    "L1"),
    (0.80, 0.95, "Level 2 - Supplier Data",   "L2"),
    (0.70, 0.85, "Level 3 - Trade Data",      "L3"),
    (0.50, 0.75, "Level 4 - Industry Average","L4"),
    (0.25, 0.50, "Level 5 - Fallback Logic",  "L5"),
]


def _score_to_label(score: float) -> dict[str, object]:
    """Map a numeric 0–1 confidence score to its level label and short code."""
    clamped = max(0.0, min(1.0, score))
    for lo, hi, label, code in _CONFIDENCE_BANDS:
        if clamped >= lo or (clamped > hi - 0.01 and clamped <= hi):
            # Edge-case: if score sits exactly on a boundary, prefer the higher band
            return {"level": code, "label": label, "score": round(clamped, 2),
                    "percent": round(clamped * 100)}
    # Below 0.25 — off-scale low
    return {"level": "L5", "label": "Level 5 - Fallback Logic", "score": round(clamped, 2),
            "percent": round(clamped * 100)}


def _min_resource_confidence(resources: dict[str, object]) -> Optional[float]:
    """Return the lowest confidence score found across machine + process breakdowns."""
    scores: list[float] = []
    for mb in resources.get("machine_breakdown", []):  # type: ignore[attr-defined]
        c = mb.get("confidence")  # type: ignore[union-attr]
        if isinstance(c, dict) and "score" in c:
            scores.append(float(c["score"]))
    for pb in resources.get("process_breakdown", []):  # type: ignore[attr-defined]
        c = pb.get("confidence")  # type: ignore[union-attr]
        if isinstance(c, dict) and "score" in c:
            scores.append(float(c["score"]))
    return min(scores) if scores else None


def build_report(
    classification: dict[str, object],
    template_match: dict[str, object],
    route: dict[str, object],
    resources: dict[str, object],
    *,
    domain: str | None = None,
) -> dict[str, object]:
    """Dispatch public-report construction to the selected domain pack."""
    pack = _resolve_pack(domain)
    return pack.report_builder.build(
        classification=classification,
        template_match=template_match,
        route=route,
        resources=resources,
    )


def _build_report(
    classification: dict[str, object],
    template_match: dict[str, object],
    route: dict[str, object],
    resources: dict[str, object],
) -> dict[str, object]:
    taxonomy = classification["taxonomy"]
    template = template_match["template"]
    route_confidence = float(route["confidence"])
    product_confidence = float(classification["confidence"])

    # Base aggregate from classification + route; template confidence is
    # currently implicit (no dedicated score) so we weight route higher.
    base_score = round((product_confidence * 0.40) + (route_confidence * 0.40) + 0.2, 2)

    # Pull in resource-level confidence if available — the weakest link
    # (typically machine energy proxies at L4) should drag the overall down.
    resource_min = _min_resource_confidence(resources)
    if resource_min is not None and resource_min < base_score:
        # Blend: 30 % resource floor + 70 % upstream score
        overall_score = round(base_score * 0.7 + resource_min * 0.3, 2)
    else:
        overall_score = base_score

    overall_level = _score_to_label(overall_score)

    return {
        "product": {
            "taxonomy_id": taxonomy["taxonomy_id"],
            "domain": taxonomy["level_1_domain"],
            "family": taxonomy["level_2_family"],
            "category": taxonomy["level_3_category"],
            "product_type": taxonomy["level_4_product_type"],
            "variant": taxonomy["level_5_subtype"],
            "template_id": template["template_id"],
            "template_name": template["template_name"],
            "weight_g": template_match["resolved_weight_g"],
            "gsm": template_match["resolved_gsm"],
            "material_blend": template_match["material_blend"],
        },
        "confidence": {
            "overall_score": overall_score,
            "overall_level": overall_level["level"],
            "overall_label": overall_level["label"],
            "overall_percent": overall_level["percent"],
            "classification_score": product_confidence,
            "classification_level": _score_to_label(product_confidence)["level"],
            "route_score": route_confidence,
            "route_level": _score_to_label(route_confidence)["level"],
            "resource_floor_score": resource_min,
            "resource_floor_level": _score_to_label(resource_min)["level"] if resource_min is not None else None,
            "match_score": classification["match_score"],
            "alternatives": classification["alternatives"],
        },
        "route": route,
        "impact": resources["totals"],
        "impact_breakdown": {
            "energy_kwh": resources["totals"].get("energy_kwh", 0.0),
            "water_l": resources["totals"].get("water_l", 0.0),
            "carbon_kgco2e": resources["totals"].get("carbon_kgco2e", 0.0),
            "electricity_carbon_kgco2e": round(
                resources["totals"].get("carbon_kgco2e", 0.0)
                - resources["totals"].get("transport_carbon_kgco2e", 0.0)
                - resources["totals"].get("chemical_carbon_kgco2e", 0.0),
                3,
            ),
            "transport_carbon_kgco2e": resources["totals"].get("transport_carbon_kgco2e", 0.0),
            "chemical_carbon_kgco2e": resources["totals"].get("chemical_carbon_kgco2e", 0.0),
        },
        "process_breakdown": resources["process_breakdown"],
        "machine_breakdown": resources["machine_breakdown"],
        "activity_trace": resources["activity_trace"],
        "chemical_inventory": resources["chemical_inventory"],
        "impact_data_quality": resources.get("impact_data_quality", {}),
        "digital_product_passport": {
            "product_type": taxonomy["level_4_product_type"],
            "route_id": route["route_id"],
            "template_id": template["template_id"],
            "kg_coverage": taxonomy["kg_coverage"],
            "source_status": route["source_mix"],
            "principles": [
                "Everything is traceable",
                "All emissions originate from activity data",
                "Inference results are stored separately from source data",
                "Confidence is a first-class attribute",
                "Knowledge Graph drives inference",
            ],
        },
    }
