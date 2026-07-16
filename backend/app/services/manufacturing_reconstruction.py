from __future__ import annotations

from app.services.knowledge_loader import load_knowledge_graph


def reconstruct_route(route_id: str) -> dict[str, object]:
    kg = load_knowledge_graph()
    steps = kg["routes_by_id"].get(route_id, [])
    source_mix = {
        "kg_backed": sum(1 for step in steps if "KG-backed" in step["kg_source_status"]),
        "inferred": sum(1 for step in steps if "inferred" in step["kg_source_status"].lower()),
        "total": len(steps),
    }

    route_confidence = 0.0
    if steps:
        route_confidence = sum(float(step["confidence_prior"]) for step in steps) / len(steps)

    return {
        "route_id": route_id,
        "route_name": steps[0]["route_name"] if steps else "Unknown route",
        "steps": steps,
        "source_mix": source_mix,
        "confidence": round(route_confidence, 2),
    }

