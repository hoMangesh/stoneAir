from __future__ import annotations

from app.services.knowledge_loader import confidence_level, load_master_data
from app.services.source_tier import adjust_activity_confidence, source_tier_from_profile


# ---------------------------------------------------------------------------
# Fallback models kept in code only where the masters lack data (water/chemical
# dosage). When the masters gain those rows, code should defer to them.
# ---------------------------------------------------------------------------

WATER_MODEL_L_PER_KG = {
    "Cotton Farming": 10000,
    "Pretreatment": 30,
    "Reactive Dyeing": 75,
    "Finishing": 10,
}

CHEMICAL_MODEL_G_PER_KG = {
    "Pretreatment": {
        "Caustic Soda": 20,
        "Wetting Agent": 5,
    },
    "Reactive Dyeing": {
        "Reactive Dye": 30,
        "Salt": 60,
        "Soda Ash": 20,
    },
    "Finishing": {
        "Softener": 10,
    },
}

# Process-level energy fallback (kWh per kg of material processed) used ONLY when
# no machine model with an energy profile resolves for a step. This implements the
# Step 3 rule "if no machines used, find probable carbon emission for the process"
# — so machineless steps (Cotton Farming, Ginning, Packaging) are not silently zero.
# Values are industry-average proxies; they get a low confidence flag so reviewers
# can see which steps still need a real machine energy profile.
PROCESS_ENERGY_FALLBACK_KWH_PER_KG = {
    "Cotton Farming": 1.2,      # diesel irrigation + tractor proxy per kg seed cotton
    "Ginning": 0.18,            # gin electricity per kg fiber
    "Packaging": 0.05,          # conveyor/press electricity per kg
    "Sole Molding": 3.1,        # footwear molding (used when no machine row exists)
    "Cementing and Sole Attachment": 0.9,
    "Finishing and Inspection": 0.4,
}

# Transport legs in the route library are phrased as prose ("Truck to gin",
# "Export transport") rather than origin->destination pairs. We map the mode
# noun found in the phrase to a transport_modes.csv row, and use the adjacent
# step countries (or a default export distance) to size the leg.
_TRANSPORT_MODE_HINTS = [
    ("air freight", "Air Freight"),
    ("ocean freight", "Ocean Freight"),
    ("ocean", "Ocean Freight"),
    ("rail", "Rail"),
    ("truck", "Truck"),
]

# Default export leg when the route says "Export transport" but no explicit
# origin->destination is known. Sized to a typical China/Vietnam -> US ocean leg.
DEFAULT_EXPORT_DISTANCE_KM = 13500
DEFAULT_EXPORT_MODE = "Ocean Freight"


def _as_float(value: str | None, default: float = 0.0) -> float:
    if value in (None, ""):
        return default
    try:
        return float(value)
    except ValueError:
        return default


def _split_pipe(value: str | None) -> list[str]:
    if not value:
        return []
    return [item.strip() for item in value.split("|") if item.strip()]


def _activity_quantity(unit: str, rate: float, weight_kg: float) -> float:
    if unit == "kWh/garment":
        return rate
    if "/kg" in unit:
        return rate * weight_kg
    return rate * weight_kg


# Process groups whose step country is origin-sensitive — the BOM's declared
# origin (where the fiber/material is grown or recovered) overrides the route's
# hardcoded default_country. Finishing steps happen where the garment is
# assembled, so they keep the route default. Mirrors route_resolution's set.
_ORIGIN_SENSITIVE_PROCESS_GROUPS = {"Fiber Production", "Fiber Preparation"}


def _canonical_country(name: str, master_data: dict[str, object] | None) -> str:
    """Normalize a country name to the masters' Title-Case key where possible.

    BOM origins arrive from document_intelligence already lowercased ("india"),
    but the masters index emission_factors / transport_routes / region_machine_rank
    by Title-Case names ("India"). Lowercasing both sides of a comparison hides the
    mismatch in route_resolution, but resource_models does direct ``.get(country)``
    lookups — so a raw lowercase origin would miss and silently fall to Default.
    Resolve through the case-insensitive country index instead. Anything not in the
    master (a free-form origin, or "Default") is returned untouched so downstream's
    own fallback handling still applies.
    """
    if not name or not master_data:
        return name
    ci = master_data.get("countries_by_name_ci") or {}
    hit = ci.get(name.strip().lower())
    return (hit.get("country_name") or name) if hit else name


def _step_country(step: dict[str, str], origin_context: dict[str, object] | None,
                  master_data: dict[str, object] | None = None) -> str:
    """Resolve a step's country, injecting the BOM origin for origin-sensitive groups.

    Without an origin_context (or for non-origin-sensitive steps) this returns the
    route's reviewed ``default_country`` — unchanged behaviour, no regression.
    With an origin_context for a farming/agro step, the BOM's origin wins so the
    grid factor and transport legs follow the real material origin, not the
    route's pre-filled default (the "origin is tentative" gap this closes). The
    origin is canonicalized to the masters' Title-Case country key so downstream
    ``.get(country)`` lookups (emission factors, transport legs, region machine
    rank) actually hit instead of falling to Default on a casing mismatch.
    """
    route_default = step.get("default_country") or "Default"
    if not origin_context:
        return route_default
    groups = origin_context.get("process_groups") or _ORIGIN_SENSITIVE_PROCESS_GROUPS
    if (step.get("process_group") or "").strip() in groups:
        origin = (origin_context.get("origin") or "").strip()
        if origin:
            return _canonical_country(origin, master_data)
    return route_default


def _select_machine_records(step: dict[str, str], master_data: dict[str, object],
                             origin_context: dict[str, object] | None = None) -> list[dict[str, str]]:
    """Pick the machine model(s) for a step.

    Region-prioritized: among models in the parked machine category, prefer the
    model most commonly installed in the step's country (factory_machine_map),
    because the same process is run on different machines by region. Falls back
    to category-default ordering when no regional install data exists. Only
    models that have a machine energy profile can contribute energy/carbon.
    """
    machine_models_by_category = master_data["machine_models_by_category"]
    machine_energy_by_model = master_data["machine_energy_by_model"]
    region_machine_rank = master_data.get("region_machine_rank", {})
    country = _step_country(step, origin_context, master_data)
    selected: list[dict[str, str]] = []

    for machine_name in _split_pipe(step.get("default_machine_names")):
        candidates = list(machine_models_by_category.get(machine_name, []))
        if not candidates:
            continue
        ranked = _rank_models_by_region(candidates, country, region_machine_rank)
        for model in ranked:
            energy_profile = machine_energy_by_model.get(model["machine_model_id"])
            if energy_profile:
                selected.append({"machine_name": machine_name, **model, **energy_profile})
                break
    return selected


def _rank_models_by_region(candidates: list[dict[str, str]], country: str, region_rank: dict) -> list[dict[str, str]]:
    """Rank machine models by install quantity in the step's country.

    Models installed in the region (highest quantity first) come first; the rest
    keep their original order as fallback. This encodes 'machine model usually
    used in that geographical region'.
    """
    if not candidates:
        return candidates
    category = candidates[0].get("machine_category", "")
    preferred = [entry["machine_model_id"] for entry in region_rank.get(country, {}).get(category, [])]
    if not preferred:
        return candidates
    # Models with a regional install rank first (by install-order/index), others last.
    return sorted(
        candidates,
        key=lambda model: preferred.index(model["machine_model_id"])
        if model["machine_model_id"] in preferred
        else len(preferred),
    )


def _electricity_factor(country: str, master_data: dict[str, object]) -> dict[str, str]:
    emission_factors_by_country = master_data["emission_factors_by_country"]
    return emission_factors_by_country.get(country) or emission_factors_by_country.get("Default", {})


def _chemical_factor(chemical_name: str, master_data: dict[str, object]) -> dict[str, str]:
    factors = master_data.get("chemical_emission_factors_by_name", {})
    return factors.get(chemical_name) or factors.get(chemical_name.strip().title(), {})


def _transport_factor(mode: str, master_data: dict[str, object]) -> tuple[float, str, float]:
    """Return (factor, factor_id, confidence) for a transport mode."""
    by_mode = master_data.get("transport_factors_by_mode", {})
    record = by_mode.get(mode) or by_mode.get(DEFAULT_EXPORT_MODE, {})
    return (
        _as_float(record.get("factor")),
        record.get("transport_id", "EF-TRANS-DEF-2026"),
        _as_float(record.get("confidence"), 0.25),
    )


def _resolve_transport_leg(
    step: dict[str, str],
    route_steps: list[dict[str, str]],
    index: int,
    master_data: dict[str, object],
    origin_context: dict[str, object] | None = None,
) -> dict[str, object] | None:
    """Turn a route step's `transport_leg_after` prose into an emissions row.

    Origin = this step's country (origin-aware: a farming/agro step uses the
    BOM's declared material origin, not the route's hardcoded default).
    Destination = next step's country if available, else a default export hub.
    Distance/mode come from transport_routes.csv when the (origin, destination)
    leg is known, else the default export distance.
    """
    leg_phrase = (step.get("transport_leg_after") or "").strip().lower()
    if not leg_phrase or leg_phrase == "none":
        return None

    route_ids_by_leg = master_data.get("transport_routes_by_leg", {})
    origin_country = _step_country(step, origin_context, master_data).strip()
    next_step = route_steps[index + 1] if index + 1 < len(route_steps) else None
    destination_country = (_step_country(next_step, origin_context, master_data) if next_step else "").strip() or "United States"

    chosen_mode = DEFAULT_EXPORT_MODE
    for needle, mode in _TRANSPORT_MODE_HINTS:
        if needle in leg_phrase:
            chosen_mode = mode
            break

    leg_record = route_ids_by_leg.get(f"{origin_country}|{destination_country}")
    distance_km = _as_float(leg_record.get("distance")) if leg_record else 0.0
    if leg_record:
        chosen_mode = leg_record.get("mode", chosen_mode) or chosen_mode
    if not distance_km:
        # "Export transport" or unmapped leg -> assume the long export haul.
        distance_km = DEFAULT_EXPORT_DISTANCE_KM
        if "export" in leg_phrase:
            chosen_mode = DEFAULT_EXPORT_MODE

    return {
        "origin": origin_country or "Default",
        "destination": destination_country or "United States",
        "mode": chosen_mode,
        "distance_km": distance_km,
    }


def estimate_resources(route_steps: list[dict[str, str]], weight_g: int,
                       origin_context: dict[str, object] | None = None) -> dict[str, object]:
    master_data = load_master_data()
    final_weight_kg = max(weight_g / 1000, 0.01)
    yield_by_process = master_data.get("yield_model_by_process", {})

    # Mass-balance: walk the route upstream applying each step's yield so earlier
    # steps (farming, spinning) process more material than the final garment mass.
    # We compute a per-step "material_mass_kg" from the final garment backward.
    step_mass_kg: list[float] = [final_weight_kg] * len(route_steps)
    working_mass = final_weight_kg
    for index in range(len(route_steps) - 1, -1, -1):
        step = route_steps[index]
        process_name = step.get("process_name", "")
        step_yield = yield_by_process.get(process_name, {})
        yield_pct = _as_float(step_yield.get("yield_percent"), None) if step_yield else None
        if yield_pct and 0 < yield_pct < 100:
            # This step's output is `working_mass`; its input had to be larger.
            step_mass_kg[index] = working_mass / (yield_pct / 100.0)
            working_mass = step_mass_kg[index]
        else:
            step_mass_kg[index] = working_mass

    process_breakdown: list[dict[str, object]] = []
    machine_breakdown: list[dict[str, object]] = []
    activity_trace: list[dict[str, object]] = []
    chemical_inventory: dict[str, float] = {}
    totals = {
        "energy_kwh": 0.0,
        "water_l": 0.0,
        "carbon_kgco2e": 0.0,
        "transport_carbon_kgco2e": 0.0,
        "chemical_carbon_kgco2e": 0.0,
    }

    for index, step in enumerate(route_steps):
        step_energy_kwh = 0.0
        step_water_l = 0.0
        step_carbon = 0.0
        step_mass = step_mass_kg[index]
        # Origin-sensitive steps (farming/agro) use the BOM origin's grid; the
        # rest keep the route default. Same helper the machine selection uses.
        country = _step_country(step, origin_context, master_data)
        factor_record = _electricity_factor(country, master_data)
        factor = _as_float(factor_record.get("factor"), 0.55)
        factor_confidence = _as_float(factor_record.get("confidence"), 0.35)
        factor_id = factor_record.get("factor_id", "EF-ELEC-DEF-2026")
        machine_records = _select_machine_records(step, master_data, origin_context)

        for machine in machine_records:
            electricity_rate = _as_float(machine.get("electricity"))
            electricity_kwh = _activity_quantity(machine.get("unit", ""), electricity_rate, step_mass)
            machine_water_l = _activity_quantity("L/kg", _as_float(machine.get("water")), step_mass)
            carbon = electricity_kwh * factor
            machine_confidence = _as_float(machine.get("confidence"), 0.35)
            activity_confidence = min(machine_confidence, factor_confidence, _as_float(step.get("confidence_prior"), 0.35))

            # Phase 3 — tier-aware confidence: a derivation is only as good as its
            # source tier. Read the persisted energy profile's approval/source and
            # adjust the activity confidence + label its evidence tier. Works fully
            # offline (reads the profile row already merged into `machine`).
            tier = source_tier_from_profile(machine, category=machine.get("machine_category", ""))
            activity_confidence, tier_label = adjust_activity_confidence(activity_confidence, tier)

            step_energy_kwh += electricity_kwh
            step_water_l += machine_water_l
            step_carbon += carbon
            totals["energy_kwh"] += electricity_kwh
            totals["water_l"] += machine_water_l
            totals["carbon_kgco2e"] += carbon

            activity = {
                "activity_type": "Electricity",
                "process_name": step["process_name"],
                "machine_model_id": machine["machine_model_id"],
                "machine_model": f"{machine['manufacturer']} {machine['model']}",
                "machine_category": machine["machine_category"],
                "activity_quantity": round(electricity_kwh, 4),
                "activity_unit": "kWh",
                "factor_id": factor_id,
                "factor": factor,
                "factor_unit": factor_record.get("unit", "kgCO2e/kWh"),
                "carbon_kgco2e": round(carbon, 4),
                "source": machine.get("source", ""),
                "approval_status": machine.get("approval_status", ""),
                "source_tier": tier.tier,
                "source_tier_label": tier_label,
                "confidence": confidence_level(activity_confidence),
            }
            activity_trace.append(activity)
            machine_breakdown.append(
                {
                    "step_order": step["step_order"],
                    "process_name": step["process_name"],
                    "machine_category": machine["machine_category"],
                    "machine_model_id": machine["machine_model_id"],
                    "machine_model": activity["machine_model"],
                    "unit": machine.get("unit", ""),
                    "electricity_rate": electricity_rate,
                    "electricity_kwh": round(electricity_kwh, 4),
                    "water_l": round(machine_water_l, 2),
                    "brochure_url": machine.get("brochure_url", ""),
                    "datasheet_url": machine.get("datasheet_url", ""),
                    "source_tier": tier.tier,
                    "confidence": activity["confidence"],
                    "source": machine.get("source", ""),
                }
            )

        water_process = step.get("water_model_process", "")
        if water_process in WATER_MODEL_L_PER_KG:
            water_l = WATER_MODEL_L_PER_KG[water_process] * step_mass
            step_water_l += water_l
            totals["water_l"] += water_l

        # Process-level fallback: if no machine energy profile resolved for this
        # step, the route still names it energy-intensive. Use a process-level
        # kWh/kg proxy so the step is not silently zero-carbon. Low confidence.
        if not machine_records and step["process_name"] in PROCESS_ENERGY_FALLBACK_KWH_PER_KG:
            fallback_rate = PROCESS_ENERGY_FALLBACK_KWH_PER_KG[step["process_name"]]
            fallback_kwh = fallback_rate * step_mass
            fallback_carbon = fallback_kwh * factor
            activity_confidence = min(0.3, factor_confidence, _as_float(step.get("confidence_prior"), 0.35))
            step_energy_kwh += fallback_kwh
            step_carbon += fallback_carbon
            totals["energy_kwh"] += fallback_kwh
            totals["carbon_kgco2e"] += fallback_carbon
            activity_trace.append(
                {
                    "activity_type": "Electricity",
                    "process_name": step["process_name"],
                    "machine_model_id": "FALLBACK",
                    "machine_model": f"{step['process_name']} (process-level proxy)",
                    "machine_category": "Process Fallback",
                    "activity_quantity": round(fallback_kwh, 4),
                    "activity_unit": "kWh",
                    "factor_id": factor_id,
                    "factor": factor,
                    "factor_unit": factor_record.get("unit", "kgCO2e/kWh"),
                    "carbon_kgco2e": round(fallback_carbon, 4),
                    "source": "Process-level energy proxy (no machine energy profile yet)",
                    "approval_status": "Fallback Logic",
                    "confidence": confidence_level(activity_confidence),
                }
            )

        # Chemicals -> dosage (g/kg) from the code model, embodied carbon from the
        # chemical emission-factor master. Each chemical in a wet-processing step
        # produces one activity row so its footprint is traceable.
        chemical_process = step.get("chemical_model_process", "")
        chemical_carbon_step = 0.0
        for chemical, dosage in CHEMICAL_MODEL_G_PER_KG.get(chemical_process, {}).items():
            grams = dosage * step_mass
            chemical_inventory[chemical] = chemical_inventory.get(chemical, 0.0) + grams
            chem_factor_record = _chemical_factor(chemical, master_data)
            chem_factor = _as_float(chem_factor_record.get("factor"), 0.0)
            if chem_factor and grams > 0:
                chem_carbon = (grams / 1000.0) * chem_factor  # kgCO2e
                chem_confidence = _as_float(chem_factor_record.get("confidence"), 0.3)
                activity_confidence = min(chem_confidence, _as_float(step.get("confidence_prior"), 0.35))
                activity_trace.append(
                    {
                        "activity_type": "Chemical",
                        "process_name": step["process_name"],
                        "machine_model_id": chem_factor_record.get("factor_id", ""),
                        "machine_model": chemical,
                        "machine_category": "Chemical",
                        "activity_quantity": round(grams / 1000.0, 4),
                        "activity_unit": "kg",
                        "factor_id": chem_factor_record.get("factor_id", "EF-CHEM-DEF"),
                        "factor": chem_factor,
                        "factor_unit": chem_factor_record.get("unit", "kgCO2e/kg"),
                        "carbon_kgco2e": round(chem_carbon, 4),
                        "source": chem_factor_record.get("source", ""),
                        "approval_status": chem_factor_record.get("approval_status", ""),
                        "confidence": confidence_level(activity_confidence),
                    }
                )
                chemical_carbon_step += chem_carbon
        totals["chemical_carbon_kgco2e"] += chemical_carbon_step
        totals["carbon_kgco2e"] += chemical_carbon_step
        step_carbon += chemical_carbon_step

        # Transport leg after this step.
        leg = _resolve_transport_leg(step, route_steps, index, master_data, origin_context)
        if leg:
            transport_factor, transport_factor_id, transport_confidence = _transport_factor(leg["mode"], master_data)
            # ton-km = product mass (tons) * distance. Use final garment mass for
            # the export leg; intra-route legs move semi-finished material.
            ton_km = (final_weight_kg / 1000.0) * leg["distance_km"]
            transport_carbon = ton_km * transport_factor
            totals["transport_carbon_kgco2e"] += transport_carbon
            totals["carbon_kgco2e"] += transport_carbon
            step_carbon += transport_carbon
            activity_trace.append(
                {
                    "activity_type": "Transport",
                    "process_name": step["process_name"],
                    "machine_model_id": transport_factor_id,
                    "machine_model": f"{leg['mode']} {leg['origin']} -> {leg['destination']}",
                    "machine_category": "Transport",
                    "activity_quantity": round(ton_km, 2),
                    "activity_unit": "ton-km",
                    "factor_id": transport_factor_id,
                    "factor": transport_factor,
                    "factor_unit": "kgCO2e/ton-km",
                    "carbon_kgco2e": round(transport_carbon, 5),
                    "source": "GLEC freight proxy",
                    "approval_status": "Pending Validation",
                    "confidence": confidence_level(min(transport_confidence, _as_float(step.get("confidence_prior"), 0.35))),
                }
            )

        process_steps = master_data["process_steps_by_process"].get(step.get("process_id", ""), [])
        process_breakdown.append(
            {
                "step_order": step["step_order"],
                "process_id": step.get("process_id", ""),
                "process_name": step["process_name"],
                "process_group": step["process_group"],
                "country": country if country != "Default" else "",
                "material_mass_kg": round(step_mass, 4),
                "energy_kwh": round(step_energy_kwh, 3),
                "water_l": round(step_water_l, 2),
                "carbon_kgco2e": round(step_carbon, 4),
                "machines": step.get("default_machine_names", ""),
                "machine_models": [item["machine_model"] for item in machine_breakdown if item["step_order"] == step["step_order"]],
                "process_steps": [
                    {"step_name": row["step_name"], "sequence": int(row["sequence"])}
                    for row in process_steps
                ],
                "source_status": step.get("kg_source_status", ""),
                "confidence": confidence_level(_as_float(step.get("confidence_prior"), 0.35)),
            }
        )

    impact_totals = {key: round(totals[key], 3) for key in totals}
    return {
        "totals": impact_totals,
        "process_breakdown": process_breakdown,
        "machine_breakdown": machine_breakdown,
        "activity_trace": activity_trace,
        "chemical_inventory": {
            chemical: round(value, 2)
            for chemical, value in sorted(chemical_inventory.items())
        },
    }
