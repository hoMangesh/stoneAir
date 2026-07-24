from __future__ import annotations

import csv
from functools import lru_cache
from pathlib import Path
from typing import Any

from app.config import MASTER_DATASETS, PRODUCT_TAXONOMY_CSV, PRODUCT_TEMPLATE_CSV, ROUTE_LIBRARY_CSV


def _read_csv(path: Path) -> list[dict[str, str]]:
    if not path.exists():
        return []
    with path.open(newline="", encoding="utf-8") as handle:
        return [dict(row) for row in csv.DictReader(handle)]


def _split_pipe(value: str | None) -> list[str]:
    if not value:
        return []
    return [item.strip() for item in value.split("|") if item.strip()]


def _index_by(rows: list[dict[str, str]], key: str) -> dict[str, dict[str, str]]:
    return {row[key]: row for row in rows if row.get(key)}


def _group_by(rows: list[dict[str, str]], key: str) -> dict[str, list[dict[str, str]]]:
    grouped: dict[str, list[dict[str, str]]] = {}
    for row in rows:
        value = row.get(key)
        if value:
            grouped.setdefault(value, []).append(row)
    return grouped


@lru_cache(maxsize=1)
def load_knowledge_graph() -> dict[str, Any]:
    taxonomy = _read_csv(PRODUCT_TAXONOMY_CSV)
    templates = _read_csv(PRODUCT_TEMPLATE_CSV)
    routes = _read_csv(ROUTE_LIBRARY_CSV)

    taxonomy_by_id = {row["taxonomy_id"]: row for row in taxonomy}
    templates_by_id = {row["template_id"]: row for row in templates}
    routes_by_id: dict[str, list[dict[str, str]]] = {}

    for row in routes:
        row["step_order"] = int(row["step_order"])
        row["taxonomy_id_list"] = _split_pipe(row.get("taxonomy_ids"))
        routes_by_id.setdefault(row["route_id"], []).append(row)

    for route_steps in routes_by_id.values():
        route_steps.sort(key=lambda item: item["step_order"])

    # Group routes by taxonomy_id for composite routing. Each route declares a
    # pipe-list `taxonomy_ids` of the products it can serve; index every route_id
    # under each of its taxonomy IDs so the resolver can ask "which routes cover
    # THIS product?" and then score them by composition/origin.
    routes_by_taxonomy: dict[str, list[dict[str, str]]] = {}
    route_meta: dict[str, dict[str, str]] = {}
    seen_route: set[str] = set()
    for row in routes:
        rid = row["route_id"]
        if rid not in route_meta:
            route_meta[rid] = row  # first row carries the route-level metadata
        if rid in seen_route:
            continue
        seen_route.add(rid)
        for tid in _split_pipe(row.get("taxonomy_ids")):
            routes_by_taxonomy.setdefault(tid, []).append(row)

    return {
        "taxonomy": taxonomy,
        "templates": templates,
        "routes": routes,
        "taxonomy_by_id": taxonomy_by_id,
        "templates_by_id": templates_by_id,
        "routes_by_id": routes_by_id,
        "routes_by_taxonomy": routes_by_taxonomy,
        "route_meta": route_meta,
    }


@lru_cache(maxsize=1)
def load_master_data() -> dict[str, Any]:
    datasets = {
        name: _read_csv(path)
        for name, path in MASTER_DATASETS.items()
    }

    machine_models_by_category = _group_by(datasets["machine_models"], "machine_category")
    machine_categories_by_name = _index_by(datasets["machine_categories"], "machine_name")
    machine_energy_by_model = _index_by(datasets["machine_energy_profiles"], "machine_model_id")
    machine_brochures_by_model = _group_by(datasets["machine_brochures"], "machine_model_id")
    machine_spec_extractions_by_model = _group_by(datasets["machine_spec_extractions"], "machine_model_id")
    # Per-material origin provenance (material_id -> [origin rows]). Drives the
    # origin-of-processes path: a BOM component's material resolves to its known
    # production countries/regions so the farming/agro steps use the real origin
    # and the grid+transport factors follow it. Falls back to the route's
    # default_country when no material-origin row matches.
    material_origins_by_material = _group_by(datasets["material_origins"], "material_id")
    countries_by_name = _index_by(datasets["countries"], "country_name")
    # Case-insensitive country canonicalizer: maps every lowercase country_name
    # to its master row, so a BOM origin arriving lowercased ("india") from
    # document_intelligence can be normalized back to the masters' Title-Case
    # keys ("India") that emission_factors / transport_routes / region_machine_rank
    # are indexed by. Without this, the origin-of-processes path would miss every
    # Title-Case lookup and silently fall to Default.
    countries_by_name_ci = {
        (row.get("country_name") or "").strip().lower(): row
        for row in datasets["countries"]
        if row.get("country_name")
    }
    emission_factors_by_country = {
        row["country"]: row
        for row in datasets["emission_factors"]
        if row.get("activity_type") == "Electricity" and row.get("country")
    }
    # Chemical emission factors: emission_factors.csv carries them as rows with
    # activity_type=Chemical and a factor_id encoding the chemical name (no
    # chemical_name column). Map the readable names used in resource_models to
    # those rows so the carbon engine can look them up.
    _CHEMICAL_FACTOR_NAME_ALIASES = {
        "Reactive Dye": "REACTIVE-DYE",
        "Salt": "SALT",
        "Caustic Soda": "CAUSTIC-SODA",
        "Soda Ash": "SODA-ASH",
        "Softener": "SOFTENER",
        "Wetting Agent": "WETTING-AGENT",
        "Adhesive": "ADHESIVE",
    }
    chemical_factor_rows = {
        row["factor_id"]: row
        for row in datasets["emission_factors"]
        if row.get("activity_type") == "Chemical" and row.get("factor")
    }
    chemical_emission_factors_by_name = {}
    for chemical_name, factor_token in _CHEMICAL_FACTOR_NAME_ALIASES.items():
        for factor_id, row in chemical_factor_rows.items():
            if factor_token in factor_id:
                chemical_emission_factors_by_name[chemical_name] = row
                break
    transport_factors_by_mode = {
        row["mode"]: row for row in datasets["transport_modes"] if row.get("mode")
    }
    transport_routes_by_leg = {
        f"{row['origin']}|{row['destination']}": row
        for row in datasets["transport_routes"]
        if row.get("origin") and row.get("destination")
    }
    yield_model_by_process = {
        row["process"]: row for row in datasets["yield_models"] if row.get("process")
    }
    process_steps_by_process = _group_by(datasets["process_steps"], "process_id")
    factory_machines_by_model = _group_by(datasets["factory_machine_map"], "machine_model_id")

    # Region -> machine models: join factories (country) to factory_machine_map
    # (model + install quantity) so Region-prioritized selection can pick the
    # most-commonly-installed model per machine category for a given country.
    factories_by_id = {row["factory_id"]: row for row in datasets["factories"] if row.get("factory_id")}
    region_machine_rank: dict[str, dict[str, list[dict[str, object]]]] = {}
    for install in datasets["factory_machine_map"]:
        factory = factories_by_id.get(install.get("factory_id", ""))
        country = (factory.get("country") if factory else "")  # normalize empty -> Default later
        country = country or "Default"
        model_id = install.get("machine_model_id")
        if not model_id:
            continue
        model_row = next((m for m in datasets["machine_models"] if m["machine_model_id"] == model_id), {})
        category = model_row.get("machine_category", "")
        entry = {"machine_model_id": model_id, "quantity": int(install.get("quantity") or 0), "category": category}
        region_machine_rank.setdefault(country, {}).setdefault(category, []).append(entry)
    for country in region_machine_rank:
        for category in region_machine_rank[country]:
            region_machine_rank[country][category].sort(key=lambda e: e["quantity"], reverse=True)

    return {
        "datasets": datasets,
        "machine_models_by_category": machine_models_by_category,
        "machine_categories_by_name": machine_categories_by_name,
        "machine_energy_by_model": machine_energy_by_model,
        "machine_brochures_by_model": machine_brochures_by_model,
        "machine_spec_extractions_by_model": machine_spec_extractions_by_model,
        "material_origins_by_material": material_origins_by_material,
        "countries_by_name": countries_by_name,
        "countries_by_name_ci": countries_by_name_ci,
        "emission_factors_by_country": emission_factors_by_country,
        "chemical_emission_factors_by_name": chemical_emission_factors_by_name,
        "transport_factors_by_mode": transport_factors_by_mode,
        "transport_routes_by_leg": transport_routes_by_leg,
        "yield_model_by_process": yield_model_by_process,
        "process_steps_by_process": process_steps_by_process,
        "factory_machines_by_model": factory_machines_by_model,
        "factories_by_country": _group_by(datasets["factories"], "country"),
        "region_machine_rank": region_machine_rank,
    }


def confidence_level(confidence: float) -> dict[str, object]:
    score = max(0.0, min(confidence, 1.0))
    percent = score * 100
    if percent >= 95:
        label = "Level 1 - Primary Data"
    elif percent >= 80:
        label = "Level 2 - Supplier Data"
    elif percent >= 70:
        label = "Level 3 - Trade Data"
    elif percent >= 50:
        label = "Level 4 - Industry Average"
    else:
        label = "Level 5 - Fallback Logic"
    return {"label": label, "score": round(score, 2), "percent": round(percent, 1)}
