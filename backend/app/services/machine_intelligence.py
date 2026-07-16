from __future__ import annotations

import re
from collections import Counter

from app.services.knowledge_loader import confidence_level, load_master_data


POWER_PATTERN = re.compile(
    r"(?P<value>\d+(?:\.\d+)?)\s*(?P<unit>kw|kilowatt|kilowatts|hp|horsepower)\b",
    re.IGNORECASE,
)
THROUGHPUT_PATTERN = re.compile(
    r"(?P<value>\d+(?:\.\d+)?)\s*(?P<unit>kg/h|kg/hr|kg per hour|kg/hour|garments/hour|pcs/min|stitches/min|rpm)\b",
    re.IGNORECASE,
)
CAPACITY_PATTERN = re.compile(
    r"(?P<value>\d+(?:\.\d+)?)\s*(?P<unit>kg|litre|liter|l|spindles|needles|feeders)\b",
    re.IGNORECASE,
)
LIQUOR_RATIO_PATTERN = re.compile(
    r"(?:liquor\s*ratio|bath\s*ratio|water\s*ratio)\D{0,20}(?P<value>\d+(?:\.\d+)?)\s*:\s*(?P<denominator>\d+(?:\.\d+)?)",
    re.IGNORECASE,
)


def _first_matches(pattern: re.Pattern[str], text: str, limit: int = 6) -> list[dict[str, str]]:
    matches: list[dict[str, str]] = []
    for match in pattern.finditer(text):
        payload = {key: value for key, value in match.groupdict().items() if value is not None}
        payload["raw"] = match.group(0)
        matches.append(payload)
        if len(matches) >= limit:
            break
    return matches


def extract_machine_specs(text: str, machine_model_id: str = "", source: str = "uploaded_text") -> dict[str, object]:
    normalized = " ".join(text.split())
    power = _first_matches(POWER_PATTERN, normalized)
    throughput = _first_matches(THROUGHPUT_PATTERN, normalized)
    capacity = _first_matches(CAPACITY_PATTERN, normalized)
    liquor_ratio = _first_matches(LIQUOR_RATIO_PATTERN, normalized)
    extracted_fields = {
        "power": power,
        "throughput": throughput,
        "capacity": capacity,
        "liquor_ratio": liquor_ratio,
    }
    populated = sum(1 for values in extracted_fields.values() if values)
    confidence = 0.25 + min(populated, 4) * 0.12

    return {
        "machine_model_id": machine_model_id,
        "source": source,
        "extracted_fields": extracted_fields,
        "candidate_record_count": sum(len(values) for values in extracted_fields.values()),
        "confidence": confidence_level(confidence),
        "storage_policy": "Extraction candidates are returned for review and should be stored as source records only after approval.",
    }


def machine_intelligence_summary() -> dict[str, object]:
    master = load_master_data()
    datasets = master["datasets"]
    brochures_by_model = master["machine_brochures_by_model"]
    specs_by_model = master["machine_spec_extractions_by_model"]
    energy_by_model = master["machine_energy_by_model"]
    factory_machines_by_model = master["factory_machines_by_model"]

    records: list[dict[str, object]] = []
    status_counter: Counter[str] = Counter()
    extraction_counter: Counter[str] = Counter()

    for model in datasets["machine_models"]:
        model_id = model["machine_model_id"]
        brochures = brochures_by_model.get(model_id, [])
        specs = specs_by_model.get(model_id, [])
        energy_profile = energy_by_model.get(model_id, {})
        factory_machines = factory_machines_by_model.get(model_id, [])
        primary_brochure = brochures[0] if brochures else {}
        status = primary_brochure.get("source_status", "Missing Brochure Record")
        extraction_status = primary_brochure.get("extraction_status", "Not Extracted")
        status_counter[status] += 1
        extraction_counter[extraction_status] += 1

        records.append(
            {
                "machine_model_id": model_id,
                "manufacturer": model["manufacturer"],
                "model": model["model"],
                "machine_category": model["machine_category"],
                "process": model["process"],
                "brochure": primary_brochure,
                "extracted_specs": specs,
                "energy_profile": energy_profile,
                "factory_installations": sum(int(row.get("quantity") or 0) for row in factory_machines),
                "confidence": confidence_level(float(model.get("confidence") or 0.25)),
                "next_action": _next_action(status, extraction_status, energy_profile),
            }
        )

    return {
        "summary": {
            "machine_models": len(datasets["machine_models"]),
            "brochure_records": len(datasets["machine_brochures"]),
            "spec_extraction_records": len(datasets["machine_spec_extractions"]),
            "energy_profiles": len(datasets["machine_energy_profiles"]),
            "source_status": dict(status_counter),
            "extraction_status": dict(extraction_counter),
        },
        "records": records,
        "extraction_fields": ["power", "throughput", "capacity", "liquor_ratio"],
    }


def _next_action(status: str, extraction_status: str, energy_profile: dict[str, str]) -> str:
    if status == "Pending Public URL":
        return "Attach verified public brochure or datasheet URL."
    if extraction_status == "Not Extracted":
        return "Run brochure text extraction and review candidate specs."
    if not energy_profile:
        return "Create machine energy profile from approved extracted specs."
    return "Review confidence and promote approval status when source is verified."
