from __future__ import annotations

import json

from fastapi import FastAPI, File, Form, UploadFile
from fastapi.middleware.cors import CORSMiddleware

from app.services.document_intelligence import (
    extract_document_signals,
    extract_text_from_uploads,
    extract_text_from_upload,
)
from app.services.brochure_pipeline import (
    brochure_review_summary,
    extract_brochure,
    fetch_brochure_text,
    promote_energy_profile,
)
from app.services.brochure_discovery import discover_energy
from app.services.inference_engine import build_inference_trace, inference_seed_records
from app.services.knowledge_loader import load_knowledge_graph, load_master_data
from app.services.machine_intelligence import extract_machine_specs, machine_intelligence_summary
from app.services.machine_workflow import infer_workflow_record, recommend_workflow
from app.services.manufacturing_reconstruction import reconstruct_route
from app.services.persistence import persistence
from app.services.product_intelligence import classify_product, match_template
from app.services.reporting import build_report
from app.services.resource_models import estimate_resources
from app.services.route_resolution import resolve_origin_context, resolve_route
from app.services.source_tier import (
    COVERAGE_STATUS_APPROVED,
    COVERAGE_STATUS_DERIVED_APPROX,
    COVERAGE_STATUS_PROXY,
    COVERAGE_STATUS_UNSUPPORTED,
    source_tier_from_profile,
)

app = FastAPI(
    title="Manufacturing Intelligence API",
    version="0.1.0",
    description="Domain-agnostic LCA + carbon-intelligence engine. Per-domain knowledge (apparel, EV battery, …) is supplied by registered domain packs; this API dispatches to the requested domain's pack. POST /api/analyze with a `domain` field to select the industry.",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:5173",
        "http://127.0.0.1:5173",
        "http://localhost:5174",
        "http://127.0.0.1:5174",
        "http://localhost:5175",
        "http://127.0.0.1:5175",
    ],
    allow_origin_regex=r"http://(localhost|127\.0\.0\.1):517\d",
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Activate installed domain plugins at backend boot. This keeps the HTTP layer
# domain-agnostic: it knows only the registry, while bootstrap owns the list of
# available packs.
from domain_packs.bootstrap import bootstrap as _bootstrap_domain_packs

_bootstrap_domain_packs()


@app.get("/api/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/api/catalog")
def catalog() -> dict[str, object]:
    kg = load_knowledge_graph()
    return {
        "taxonomy_count": len(kg["taxonomy"]),
        "template_count": len(kg["templates"]),
        "route_count": len(kg["routes_by_id"]),
        "taxonomy": kg["taxonomy"],
        "templates": kg["templates"],
        "routes": [
            {
                "route_id": route_id,
                "route_name": steps[0]["route_name"],
                "steps": len(steps),
                "confidence": round(sum(float(step["confidence_prior"]) for step in steps) / len(steps), 2),
            }
            for route_id, steps in kg["routes_by_id"].items()
        ],
    }


@app.get("/api/master-domains")
def master_domains() -> dict[str, object]:
    master = load_master_data()
    datasets = master["datasets"]
    return {
        "principles": [
            "Everything is traceable.",
            "All emissions originate from activity data.",
            "Inference results are stored separately from source data.",
            "Confidence is a first-class attribute.",
            "Knowledge Graph drives inference.",
        ],
        "domains": [
            {"domain": "Product Master", "entity_count": len(datasets["products"])},
            {"domain": "Material Master", "entity_count": len(datasets["materials"])},
            {"domain": "Process Master", "entity_count": len(datasets["processes"])},
            {"domain": "Machine Master", "entity_count": len(datasets["machine_categories"])},
            {"domain": "Machine Model Master", "entity_count": len(datasets["machine_models"])},
            {"domain": "Consumable Master", "entity_count": len(datasets["consumables"])},
            {"domain": "Chemical Master", "entity_count": len(datasets["chemicals"])},
            {"domain": "Country Master", "entity_count": len(datasets["countries"])},
            {"domain": "Supplier Master", "entity_count": len(datasets["suppliers"])},
            {"domain": "Factory Master", "entity_count": len(datasets["factories"])},
            {"domain": "Transport Master", "entity_count": len(datasets["transport_modes"])},
            {"domain": "Emission Factor Master", "entity_count": len(datasets["emission_factors"])},
        ],
        "operational_domains": [
            {"domain": "Yield Model", "entity_count": len(datasets["yield_models"])},
            {"domain": "Material Provenance", "entity_count": len(datasets["material_origins"])},
            {"domain": "Process Step", "entity_count": len(datasets["process_steps"])},
            {"domain": "Factory Machine Map", "entity_count": len(datasets["factory_machine_map"])},
            {"domain": "Machine Brochure Repository", "entity_count": len(datasets["machine_brochures"])},
            {"domain": "Machine Spec Extraction", "entity_count": len(datasets["machine_spec_extractions"])},
        ],
        "sample_records": {
            "machine_models": datasets["machine_models"][:4],
            "machine_brochures": datasets["machine_brochures"][:4],
            "machine_energy_profiles": datasets["machine_energy_profiles"][:4],
            "emission_factors": datasets["emission_factors"][:6],
        },
    }


@app.get("/api/knowledge-graph/schema")
def knowledge_graph_schema() -> dict[str, object]:
    return {
        "nodes": [
            "Product",
            "Material",
            "Route",
            "Process",
            "ProcessStep",
            "MachineCategory",
            "MachineModel",
            "Consumable",
            "Chemical",
            "Supplier",
            "Factory",
            "Country",
            "Transport",
            "EmissionFactor",
        ],
        "relationships": [
            {"from": "Product", "relationship": "CONTAINS", "to": "Material"},
            {"from": "Material", "relationship": "FOLLOWS", "to": "Route"},
            {"from": "Route", "relationship": "HAS_PROCESS", "to": "Process"},
            {"from": "Process", "relationship": "HAS_STEP", "to": "ProcessStep"},
            {"from": "Process", "relationship": "USES", "to": "MachineCategory"},
            {"from": "MachineCategory", "relationship": "HAS_MODEL", "to": "MachineModel"},
            {"from": "MachineModel", "relationship": "CONSUMES", "to": "Consumable"},
            {"from": "Factory", "relationship": "OWNS", "to": "MachineModel"},
            {"from": "Country", "relationship": "HAS", "to": "EmissionFactor"},
            {"from": "Transport", "relationship": "USES", "to": "EmissionFactor"},
        ],
        "confidence_framework": [
            {"level": 1, "label": "Primary Data", "range": "95-99%"},
            {"level": 2, "label": "Supplier Data", "range": "80-95%"},
            {"level": 3, "label": "Trade Data", "range": "70-85%"},
            {"level": 4, "label": "Industry Average", "range": "50-75%"},
            {"level": 5, "label": "Fallback Logic", "range": "25-50%"},
        ],
        "versioning_fields": ["version", "effective_date", "expiry_date", "source", "approval_status"],
    }


@app.get("/api/inference-records")
def inference_records(limit: int = 50) -> dict[str, object]:
    """Return recently persisted reconstruction runs (DB with CSV fallback)."""
    runs = persistence.list_recent_runs(limit=min(limit, 200))
    return {
        "record_count": len(runs),
        "runs": runs,
        "storage_policy": "Runtime reconstruction runs are persisted to the database (or CSV fallback); masters remain the single source of truth.",
    }


@app.get("/api/machine-intelligence")
def machine_intelligence() -> dict[str, object]:
    return machine_intelligence_summary()


@app.get("/api/workflow")
def workflow(product_name: str) -> dict[str, object]:
    """Dynamic per-product machine workflow from the recommender — works for any name."""
    result = recommend_workflow(product_name)
    if result is None:
        return {"resolved": None, "workflow": [], "confidence": {"label": "Level 5 - Fallback Logic", "score": 0.0, "percent": 0.0}}
    return result


@app.post("/api/machine-spec-extract")
async def machine_spec_extract(
    machine_model_id: str = Form(default=""),
    brochure_text: str = Form(default=""),
    file: UploadFile | None = File(default=None),
) -> dict[str, object]:
    text_parts = [brochure_text]
    source = "pasted_text"
    if file is not None:
        raw = await file.read()
        source = file.filename or "uploaded_file"
        try:
            text_parts.append(raw.decode("utf-8"))
        except UnicodeDecodeError:
            text_parts.append(source)

    return extract_machine_specs(
        text="\n".join(part for part in text_parts if part),
        machine_model_id=machine_model_id,
        source=source,
    )


@app.get("/api/brochure-review")
def brochure_review() -> list[dict]:
    """List each machine model's current (proxy) energy profile awaiting a brochure derivation."""
    return brochure_review_summary()


@app.post("/api/brochure-review")
async def brochure_review_extract(
    machine_model_id: str = Form(default=""),
    brochure_text: str = Form(default=""),
    file: UploadFile | None = File(default=None),
) -> dict[str, object]:
    """Extract specs + DERIVE a kWh-per-unit energy profile from brochure text.

    Returns a review candidate only — does NOT write to masters (governance:
    extraction is source evidence). Call /api/brochure-promote to stamp an
    approved derivation into machine_energy_profiles.csv.
    """
    source = "pasted_text"
    pieces: list[str] = [brochure_text]
    if file is not None:
        source = file.filename or "uploaded_file"
        pieces.append(await extract_text_from_upload(file))
    return extract_brochure(machine_model_id, "\n".join(p for p in pieces if p), source)


@app.post("/api/brochure-promote")
def brochure_promote(
    machine_model_id: str = Form(...),
    derived_kwh_per_unit: float = Form(...),
    unit: str = Form(default="kWh/kg"),
    source: str = Form(default="manual_review"),
) -> dict[str, object]:
    """Promote an approved brochure-derived kWh-per-unit into the energy profiles master."""
    return promote_energy_profile(machine_model_id, derived_kwh_per_unit, unit=unit, source=source)


@app.post("/api/brochure-fetch")
def brochure_fetch(
    machine_model_id: str = Form(...),
    url: str = Form(...),
) -> dict[str, object]:
    """Fetch a real brochure/datasheet URL, extract text, and derive a candidate energy profile.

    Review-only: returns the candidate derivation; does NOT write to masters.
    Call /api/brochure-promote with the derived value to stamp it into the energy profiles.
    """
    fetched = fetch_brochure_text(url)
    if not fetched.get("text"):
        return {"machine_model_id": machine_model_id, "url": url, "error": fetched.get("error", "no extractable text")}
    return extract_brochure(machine_model_id, fetched["text"], source=url)


@app.get("/api/brochure-coverage")
def brochure_coverage(live: bool = False) -> dict[str, object]:
    """Honest coverage sweep over the CURRENT machine catalog.

    For every machine model in ``machine_models`` (the 6 seed rows + the
    catalog-bridge MMODR rows — 52 energy-bearing machines once the bridge
    lands; the 6 non-energy recommender categories are skipped), report its
    energy-profile state and the derivation-rule coverage, plus an aggregate
    derived-vs-proxy-vs-unsupported ratio that becomes the confidence signal for
    the whole carbon layer.

    Offline by default (resolved from persisted profiles + the derivation rules
    registry): no network, instant. With ``?live=true`` run live discovery per
    machine (capped as on /api/analyze) — opt-in like ``enrich_machines``.
    """
    from collections import Counter

    from app.services.derivation_rules import has_category_rule

    master = load_master_data()
    machine_energy_by_model = master["machine_energy_by_model"]
    models = master["datasets"]["machine_models"]

    # Live discovery cap, mirroring /api/analyze so a coverage sweep can't hang.
    _MAX_LIVE = 3
    live_used = 0

    rows: list[dict] = []
    for model in models:
        model_id = model["machine_model_id"]
        category = model.get("machine_category", "")
        profile = machine_energy_by_model.get(model_id, {})
        tier = source_tier_from_profile(profile, category=category)
        rule_supported = has_category_rule(category)

        profile_status = COVERAGE_STATUS_PROXY
        derivation_basis = "KG proxy energy profile (pending brochure derivation)"
        source_tier = tier.tier

        if not profile:
            profile_status = COVERAGE_STATUS_UNSUPPORTED if not rule_supported else COVERAGE_STATUS_PROXY
            derivation_basis = "no energy profile row; KG-proxy retained" if rule_supported else "no profile + no derivation rule"
            source_tier = "unsupported" if not rule_supported else "none"
        elif "brochure approved" in (profile.get("approval_status") or "").lower() \
                or "brochure-derived" in (profile.get("source") or "").lower():
            profile_status = COVERAGE_STATUS_APPROVED
            derivation_basis = f"DB-approved: {profile.get('source', '')}"
            source_tier = "manufacturer"
        elif live and live_used < _MAX_LIVE:
            result = discover_energy(model_id)
            live_used += 1
            if result.derived_kwh_per_unit is not None and not result.cache_hit:
                profile_status = COVERAGE_STATUS_DERIVED_APPROX
                derivation_basis = result.basis
                source_tier = "manufacturer"

        if not rule_supported and profile_status == COVERAGE_STATUS_PROXY:
            # A proxy on an unsupported-rule category is the queue signal (Phase 4).
            profile_status = COVERAGE_STATUS_UNSUPPORTED

        rows.append({
            "machine_model_id": model_id,
            "manufacturer": model.get("manufacturer", ""),
            "model": model.get("model", ""),
            "machine_category": category,
            "process": model.get("process", ""),
            "profile_status": profile_status,
            "source_tier": source_tier,
            "source_tier_label": tier.label,
            "derivation_basis": derivation_basis,
            "current_kwh": profile.get("electricity", ""),
            "current_unit": profile.get("unit", ""),
            "approval_status": profile.get("approval_status", ""),
            "rule_supported": rule_supported,
        })

    counts = Counter(r["profile_status"] for r in rows)
    total = len(rows)
    return {
        "live": live,
        "machines": rows,
        "aggregate": {
            "total": total,
            "approved": counts.get(COVERAGE_STATUS_APPROVED, 0),
            "derived_approx": counts.get(COVERAGE_STATUS_DERIVED_APPROX, 0),
            "proxy": counts.get(COVERAGE_STATUS_PROXY, 0),
            "unsupported": counts.get(COVERAGE_STATUS_UNSUPPORTED, 0),
            "ratio_approved": round((counts.get(COVERAGE_STATUS_APPROVED, 0) + counts.get(COVERAGE_STATUS_DERIVED_APPROX, 0)) / total, 3) if total else 0.0,
        },
    }


def _enrich_route_machines(machine_breakdown: list[dict], *, enrich: bool) -> dict[str, object]:
    """Resolve near-exact brochure-derived energy for each machine used on the route.

    When `enrich` is False (default) this returns the energy-profile approval
    status for each model used, so the UI can flag which machines still run on a
    KG-proxy vs. a brochure-approved value — no network call, instant.
    When `enrich` is True, for every machine whose profile is not yet
    brochure-approved we run live web discovery (brochure -> tech docs -> gov ->
    open LCA) and attach the derivation as an approximate candidate. Any failure
    keeps the existing proxy; this never breaks analyze.
    """
    seen: dict[str, dict] = {}
    for row in machine_breakdown:
        model_id = row.get("machine_model_id")
        if model_id and model_id not in seen:
            seen[model_id] = {
                "machine_model_id": model_id,
                "machine_model": row.get("machine_model", ""),
                "process_name": row.get("process_name", ""),
                "current_kwh": row.get("electricity_rate"),
                "current_unit": row.get("unit", ""),
                "source_status": "KG proxy",
            }

    if not enrich:
        return {"enabled": False, "machines": list(seen.values())}

    # Cap live discovery per request: each uncovered machine can cost up to
    # ~_TOTAL_TIMEOUT of web time, so bound the worst-case analyze latency.
    # The costliest drivers (dyeing, knitting) come first because they dominate
    # carbon; the rest keep showing as KG-proxy candidates for later enrichment.
    _MAX_LIVE_PER_REQUEST = 3
    enriched: list[dict] = []
    live_count = 0
    for model_id, info in seen.items():
        # Cache hits are free; only brand-new web discovery is capped.
        if live_count >= _MAX_LIVE_PER_REQUEST:
            info["source_status"] = "Discovery deferred (per-request cap); KG proxy retained"
            info["derivation_basis"] = "Skipped to keep analyze quick; run /api/brochure-fetch for this model."
            enriched.append(info)
            continue
        result = discover_energy(model_id)
        if not result.cache_hit:
            live_count += 1
        info["cache_hit"] = result.cache_hit
        if result.derived_kwh_per_unit is not None:
            info["source_status"] = "DB-approved" if result.cache_hit else "Brochure-derived (approximate)"
            info["derived_kwh_per_unit"] = result.derived_kwh_per_unit
            info["unit"] = result.unit
            info["installed_power_kw"] = result.installed_power_kw
            info["throughput_kg_per_h"] = result.throughput_kg_per_h
            info["derivation_basis"] = result.basis
        else:
            info["source_status"] = "No derivation found; KG proxy retained"
            info["derivation_basis"] = result.basis
        info["attempts"] = [
            {
                "strategy": a.strategy,
                "url": a.url,
                "outcome": a.outcome,
                "basis": a.basis,
            }
            for a in result.attempts
        ]
        enriched.append(info)
    return {"enabled": True, "machines": enriched}


@app.post("/api/analyze")
async def analyze_product(
    product_description: str = Form(default=""),
    bom: str = Form(default=""),
    origin: str = Form(default=""),
    enrich_machines: bool = Form(default=False),
    domain: str = Form(default=""),
    files: list[UploadFile] = File(default=[]),
) -> dict[str, object]:
    # Validate / resolve the domain up front. A *named-but-unknown* domain raises
    # explicitly (never a silent apparel fallback — that would fabricate an apparel
    # LCA for a battery). Empty/absent domain resolves to the apparel default so
    # existing call sites keep their behaviour (parity).
    from app.core.domain_registry import known, resolve, UnknownDomainError
    from domain_packs.bootstrap import bootstrap

    bootstrap()
    if domain and domain.strip():
        try:
            resolved_pack = resolve(domain)
        except UnknownDomainError as exc:
            from fastapi import HTTPException
            raise HTTPException(
                status_code=400,
                detail=f"unknown domain: {domain!r}; known: {known()}",
            ) from exc
        domain_id = resolved_pack.domain_id
    else:
        domain_id = resolve(None).domain_id

    # Structured BOM (materials + weight + origin) is the primary accurate path.
    # It is supplied as a JSON string so multipart forms stay simple. Missing or
    # malformed BOM degrades gracefully to the free-text description fallback.
    bom_components: list[dict] = []
    if bom.strip():
        try:
            parsed_bom = json.loads(bom)
            bom_components = parsed_bom.get("components", parsed_bom) if isinstance(parsed_bom, dict) else parsed_bom
            if not isinstance(bom_components, list):
                bom_components = []
        except json.JSONDecodeError:
            bom_components = []

    # Parse uploaded tech packs (PDF/Excel/CSV) into text rather than just
    # decoding bytes — extracts real BOM signals where the format supports it.
    uploaded_texts = await extract_text_from_uploads(files)

    signals = extract_document_signals(
        product_description,
        uploaded_texts,
        bom_components=bom_components,
        declared_origin=origin or None,
    )
    classification = classify_product(signals, domain=domain_id)
    taxonomy = classification["taxonomy"]
    template_match = match_template(str(taxonomy["taxonomy_id"]), signals, domain=domain_id)
    template = template_match["template"]
    # Composite routing: derive the route from (product type × material composition ×
    # origin) rather than taxonomy-id alone. The resolver scores the routes that cover
    # this taxonomy against the BOM's composition (Route Library inference_triggers)
    # and origin (material_origins), and falls back to the template's default_route_id
    # when nothing more specific wins. Identical signature -> identical route (memoized).
    composite_route = resolve_route(str(taxonomy["taxonomy_id"]), signals,
                                    default_route_id=str(template["default_route_id"]), domain=domain_id)
    route = reconstruct_route(composite_route["route_id"])
    # Origin-of-processes: thread the resolved BOM origin into resource_models so the
    # farming/agro steps use the real material origin's grid factor + transport legs
    # instead of the route's hardcoded default_country (the "tentative origin" gap).
    origin_context = resolve_origin_context(signals, domain=domain_id)
    resources = estimate_resources(
        route["steps"],
        int(template_match["resolved_weight_g"]),
        origin_context=origin_context,
        domain=domain_id,
    )
    report = build_report(classification, template_match, route, resources, domain=domain_id)

    # Step 4b: live machine-energy discovery. Off by default so the fast path
    # stays fast and never hits the network; opt in with enrich_machines=true.
    # For each machine model used on this route whose energy profile is still a
    # KG-proxy (not yet brochure-promoted), resolve a near-exact kWh-per-unit
    # from authentic web sources (brochure -> tech docs -> gov DBs -> open LCA).
    # Falls back to the existing proxy on any failure so analyze never breaks.
    brochure_enrichment = _enrich_route_machines(resources["machine_breakdown"], enrich=enrich_machines)

    # Dynamic per-name machine workflow from the recommender — enrichment that
    # resolves machines for products the static route library only covers generically.
    workflow_name = signals.product_hint or product_description.strip() or ""
    dynamic_workflow = recommend_workflow(workflow_name) if workflow_name else None
    workflow_record = infer_workflow_record(workflow_name) if workflow_name else None

    inference_trace = build_inference_trace(
        signals=signals,
        classification=classification,
        template_match=template_match,
        route=route,
        resources=resources,
        composite_route=composite_route,
    )
    if workflow_record:
        inference_trace["records"].insert(len(inference_trace["records"]) - (1 if resources["activity_trace"] else 0), workflow_record)
        inference_trace["summary"]["record_count"] = len(inference_trace["records"])

    # Persist this reconstruction for future reference (DB with CSV fallback).
    persisted = persistence.store_run(
        product_name=report["product"]["template_name"],
        template_id=report["product"]["template_id"],
        route_id=report["route"]["route_id"],
        totals=resources["totals"],
        inference_records=inference_trace["records"],
        activity_trace=resources["activity_trace"],
    )

    return {
        "signals": {
            "product_hint": signals.product_hint,
            "keywords": signals.keywords,
            "blend": signals.blend,
            "gsm": signals.gsm,
            "weight_g": signals.weight_g,
            "bom_components": [
                {
                    "material": component.material,
                    "percent": component.percent,
                    "weight_g": component.weight_g,
                    "origin": component.origin,
                }
                for component in signals.bom_components
            ],
            "declared_origin": signals.declared_origin,
            "provenance": signals.provenance,
        },
        "inference_trace": inference_trace,
        "dynamic_workflow": dynamic_workflow,
        "brochure_enrichment": brochure_enrichment,
        "persisted": persisted,
        **report,
    }
