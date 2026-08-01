from __future__ import annotations

import re
from collections import Counter

from app.services.knowledge_loader import confidence_level, load_master_data


# Watts included (w|watts) because garment-machine motors (e.g. a sewing
# machine DDL-8700 "550 W") quote installed power in W, not kW. The value is
# digit-prefixed and the unit is a full \b token, so "20 Width" never matches
# (the W there has no trailing word boundary). Order keeps kw/kilowatt first so
# kW figures (the derivation-grade unit) are preferred when both appear.
POWER_PATTERN = re.compile(
    r"(?P<value>\d+(?:\.\d+)?)\s*(?P<unit>kw|kilowatt|kilowatts|hp|horsepower|w|watts)\b",
    re.IGNORECASE,
)
THROUGHPUT_PATTERN = re.compile(
    r"(?P<value>\d+(?:,\d{3})*(?:\.\d+)?)\s*(?P<unit>kg/h|kg/hr|kg per hour|kg/hour|garments/hour|pcs/min|stitches/min|sti/min|rpm)\b",
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
# Cycle time for batch processes (dyeing, washing): "cycle time 45 min", "process 60 min",
# "cycle time: 1.5 h". Used to convert installed power to kWh per batch.
CYCLE_TIME_PATTERN = re.compile(
    r"(?:cycle\s*time|process\s*time|cycle\s*duration)\D{0,12}(?P<value>\d+(?:\.\d+)?)\s*"
    r"(?P<unit>h|hr|hrs|hour|hours|min|mins|minutes)\b",
    re.IGNORECASE,
)
# Batch / load capacity in kg of material (dyeing machine max load).
BATCH_KG_PATTERN = re.compile(
    r"(?:max\s*(?:load|batch|capacity|charge)|batch\s*(?:size|capacity|load)|load\s*size|charging\s*capacity)"
    r"\D{0,12}(?P<value>\d+(?:\.\d+)?)\s*(?P<unit>kg)\b",
    re.IGNORECASE,
)
# Linear feed / cutting speed and fabric width — per-area derivation for cutters/spreaders.
LINEAR_SPEED_PATTERN = re.compile(
    r"(?:cut(?:ting)?\s*speed|feed\s*speed|spreading\s*speed|line\s*speed|speed)\D{0,12}"
    r"(?P<value>\d+(?:\.\d+)?)\s*(?P<unit>m/min|m/min\.|meters/min|metres/min|m/s)\b",
    re.IGNORECASE,
)
WIDTH_PATTERN = re.compile(
    r"(?:working\s*width|fabric\s*width|cutting\s*width|width)\D{0,12}(?P<value>\d+(?:\.\d+)?)\s*"
    r"(?P<unit>m|metre|meter|cm|mm)\b",
    re.IGNORECASE,
)
# Area throughput for printing/coating (m2/h or m2/s).
AREA_THROUGHPUT_PATTERN = re.compile(
    r"(?P<value>\d+(?:\.\d+)?)\s*(?P<unit>m2/h|m2/hr|m2/hour|m²/h|m²/hour|sqm/h|sqm/hour)\b",
    re.IGNORECASE,
)


def _num(raw: str) -> float:
    """Parse a numeric match-group, tolerating thousands separators (``5,000`` -> 5000)."""
    return float(raw.replace(",", ""))


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
            # Phase 3 — honest brochure-coverage ratio over the current catalog:
            # the derived-vs-proxy split that becomes the confidence signal for
            # the whole carbon layer. Computed offline from persisted profiles.
            "brochure_coverage": _brochure_coverage_summary(datasets["machine_models"], energy_by_model),
        },
        "records": records,
        "extraction_fields": ["power", "throughput", "capacity", "liquor_ratio"],
    }


def _brochure_coverage_summary(machine_models: list[dict], energy_by_model: dict) -> dict[str, object]:
    """Aggregate derived-vs-proxy-vs-unsupported coverage over the catalog.

    Offline: reads persisted energy profiles + the derivation-rule registry. No
    live discovery here (live is opt-in on /api/brochure-coverage). Mirrors the
    endpoint's aggregate so /api/machine-intelligence surfaces the same ratio."""
    from app.services.derivation_rules import has_category_rule
    from app.services.source_tier import (
        COVERAGE_STATUS_APPROVED,
        COVERAGE_STATUS_DERIVED_APPROX,
        COVERAGE_STATUS_PROXY,
        COVERAGE_STATUS_UNSUPPORTED,
        source_tier_from_profile,
    )

    approved = derived = proxy = unsupported = 0
    for model in machine_models:
        model_id = model["machine_model_id"]
        category = model.get("machine_category", "")
        profile = energy_by_model.get(model_id, {})
        rule_supported = has_category_rule(category)
        approval = (profile.get("approval_status") or "").lower()
        source = (profile.get("source") or "").lower()
        if profile and ("brochure approved" in approval or "brochure-derived" in source):
            approved += 1
        elif profile and rule_supported:
            proxy += 1
        elif not rule_supported:
            unsupported += 1
        else:
            proxy += 1
    total = len(machine_models)
    return {
        "total": total,
        "approved": approved,
        "derived_approx": derived,
        "proxy": proxy,
        "unsupported": unsupported,
        "ratio_approved": round((approved + derived) / total, 3) if total else 0.0,
    }


def _next_action(status: str, extraction_status: str, energy_profile: dict[str, str]) -> str:
    if status == "Pending Public URL":
        return "Attach verified public brochure or datasheet URL."
    if extraction_status == "Not Extracted":
        return "Run brochure text extraction and review candidate specs."
    if not energy_profile:
        return "Create machine energy profile from approved extracted specs."
    return "Review confidence and promote approval status when source is verified."
