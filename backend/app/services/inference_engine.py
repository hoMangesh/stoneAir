from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from app.config import INFERENCE_RECORDS_CSV
from app.services.knowledge_loader import _read_csv, confidence_level


def _record(
    *,
    inference_id: str,
    inference_type: str,
    input_data: str,
    output_data: str,
    agent: str,
    confidence: float,
    source: str,
    evidence: list[str],
    approval_status: str = "Runtime Inference",
) -> dict[str, object]:
    return {
        "inference_id": inference_id,
        "inference_type": inference_type,
        "input_data": input_data,
        "output_data": output_data,
        "agent": agent,
        "confidence": confidence_level(confidence),
        "timestamp": datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z"),
        "version": "0.1",
        "source": source,
        "approval_status": approval_status,
        "evidence": evidence,
    }


def inference_seed_records() -> list[dict[str, str]]:
    return _read_csv(INFERENCE_RECORDS_CSV)


def build_inference_trace(
    *,
    signals: Any,
    classification: dict[str, object],
    template_match: dict[str, object],
    route: dict[str, object],
    resources: dict[str, object],
    composite_route: dict[str, object] | None = None,
) -> dict[str, object]:
    taxonomy = classification["taxonomy"]
    template = template_match["template"]
    route_steps = route["steps"]
    source_mix = route["source_mix"]
    machine_breakdown = resources["machine_breakdown"]
    activity_trace = resources["activity_trace"]

    inferred_step_count = int(source_mix["inferred"])
    total_step_count = max(int(source_mix["total"]), 1)
    machine_count = len(machine_breakdown)
    activity_count = len(activity_trace)
    chemical_count = len(resources["chemical_inventory"])

    records = [
        _record(
            inference_id="INF-RUN-CLASSIFICATION",
            inference_type="Product Classification",
            input_data=signals.product_hint or signals.source_text[:140] or "Uploaded product signals",
            output_data=f"{taxonomy['taxonomy_id']} - {taxonomy['level_4_product_type']} / {taxonomy['level_5_subtype']}",
            agent="Product Intelligence Agent",
            confidence=float(classification["confidence"]),
            source="Product taxonomy keywords, material blend, GSM, and description signals",
            evidence=[
                f"match_score={classification['match_score']}",
                f"keywords={', '.join(signals.keywords[:8]) or 'none'}",
                f"alternatives={len(classification['alternatives'])}",
            ],
        ),
        _record(
            inference_id="INF-RUN-TEMPLATE",
            inference_type="Template Match",
            input_data=str(taxonomy["taxonomy_id"]),
            output_data=f"{template['template_id']} - {template['template_name']}",
            agent="Product Template Agent",
            confidence=float(template.get("confidence_prior") or 0.5),
            source=str(template.get("source_basis") or "Product Template Library V1"),
            evidence=[
                f"resolved_weight_g={template_match['resolved_weight_g']}",
                f"resolved_gsm={template_match['resolved_gsm']}",
                f"default_route_id={template['default_route_id']}",
            ],
        ),
        _record(
            inference_id="INF-RUN-ROUTE",
            inference_type="Route Reconstruction",
            input_data=str(template["default_route_id"]),
            output_data=f"{route['route_id']} - {route['route_name']}",
            agent="Route Reconstruction Agent",
            confidence=float(route["confidence"]),
            source="Route Library V2",
            evidence=[
                f"steps={source_mix['total']}",
                f"kg_backed={source_mix['kg_backed']}",
                f"inferred={source_mix['inferred']}",
            ],
        ),
    ]

    if composite_route:
        sig = composite_route.get("signature") or []
        level = str(composite_route.get("confidence_level") or "L4")
        confidence = {"L3": 0.7, "L4": 0.5}.get(level, 0.5)
        records.append(
            _record(
                inference_id="INF-RUN-COMPOSITE-ROUTE",
                inference_type="Composite Route Resolution",
                input_data=" | ".join(str(part) for part in sig) or str(template["default_route_id"]),
                output_data=f"{composite_route.get('route_id')} ({level}, candidates={composite_route.get('candidates_seen')})",
                agent="Route Resolution Agent",
                confidence=confidence,
                source="Route Library V2 inference_triggers + material_origins composite scoring",
                evidence=[
                    f"derivation={str(composite_route.get('derivation_basis'))[:140]}",
                    f"fallback={composite_route.get('is_fallback')}",
                    f"bom_origin={composite_route.get('bom_origin') or 'none'}",
                ],
            ),
        )

    records.append(
        _record(
            inference_id="INF-RUN-MACHINE-RESOURCE",
            inference_type="Machine And Resource Estimation",
            input_data=f"{len(route_steps)} route steps at {template_match['resolved_weight_g']} g",
            output_data=f"{machine_count} machine mappings, {activity_count} activity rows, {chemical_count} chemicals",
            agent="Resource Model Agent",
            confidence=max(0.35, min(0.95, float(route["confidence"]) - (inferred_step_count / total_step_count * 0.12))),
            source="Machine energy profiles, water models, chemical models, and route defaults",
            evidence=[
                f"energy_kwh={resources['totals']['energy_kwh']}",
                f"water_l={resources['totals']['water_l']}",
                f"carbon_kgco2e={resources['totals']['carbon_kgco2e']}",
            ],
        ),
    )

    if activity_trace:
        activity_confidence = sum(float(row["confidence"]["score"]) for row in activity_trace) / len(activity_trace)
        records.append(
            _record(
                inference_id="INF-RUN-EMISSIONS",
                inference_type="Emission Calculation",
                input_data=f"{activity_count} activity rows",
                output_data=f"{resources['totals']['carbon_kgco2e']} kgCO2e",
                agent="Emission Engine",
                confidence=activity_confidence,
                source="Emission factor master and activity data trace",
                evidence=sorted({str(row["factor_id"]) for row in activity_trace}),
            )
        )

    return {
        "summary": {
            "record_count": len(records),
            "seed_record_count": len(inference_seed_records()),
            "storage_policy": "Runtime inference records are returned in the API response; seed records remain in data/inference/inference_records.csv until persistence is enabled.",
            "next_persistence_target": "PostgreSQL inference_records table",
        },
        "records": records,
    }
