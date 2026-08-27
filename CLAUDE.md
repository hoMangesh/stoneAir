# OneClick-LCA-Apparel

A manufacturing-intelligence engine that reconstructs a full apparel/footwear
LCA — process flow, machines, energy, water, chemicals, transport, and carbon —
from minimal input (a product name and/or a **Bill of Materials**: materials,
weights, origins, optionally a tech-pack file).

The system deliberately separates *source truth* (CSV masters under `data/`)
from *runtime inference* (the DB/CSV persistence layer), and emits a confidence
score plus a full activity trace on every reconstruction.

## Repo layout

- `backend/` — FastAPI app. `app/main.py` exposes the endpoints; `app/services/`
  holds the pipeline (see below). Run from `backend/` with its own `.venv`.
- `frontend/` — single-file React 19 + Vite SPA (`src/main.tsx`).
- `machine_recommender/` — standalone per-name machine-workflow inference
  (52 machines, fuzzy product-name parsing). Imported by the backend as a
  package via `backend/app/services/machine_workflow.py`.
- `data/masters/` — 22 CSV master tables (the knowledge graph). Source of truth.
- `data/Products/`, `data/templates/`, `data/routes/` — taxonomy / templates /
  Route Library V2 (the step-by-step process routes).
- `data/calculations/` — runtime persistence (SQLite `lca_intelligence.db`
  + CSV fallbacks). Never hand-edit; masters stay the source of truth.
- `docs/Architecture.md`, `docs/Inference_Engine.md`,
  `docs/Machine_Intelligence.md` — load-bearing design docs.

## The inference pipeline (POST /api/analyze)

`app/main.py::analyze_product` chains:

1. `document_intelligence.extract_document_signals` — reads description +
   structured BOM (`bom` JSON: materials/percent/weight_g/origin) + uploaded
   PDF/Excel/CSV files. Structured BOM wins over regex; tracks `provenance`.
2. `product_intelligence.classify_product` → taxonomy match (e.g. T-Shirt).
3. `product_intelligence.match_template` → resolves weight/gsm/blend.
4. `manufacturing_reconstruction.reconstruct_route` → the farming→final
   route steps from Route Library V2.
5. `resource_models.estimate_resources` — the carbon engine:
   - **yield mass-balance**: applies per-process yields so upstream steps
     process more material than the final garment (sourced from
     `yield_models.csv`).
   - **machine energy** → kWh → × country grid factor (electricity carbon).
   - **process-level fallback** (`PROCESS_ENERGY_FALLBACK_KWH_PER_KG`): when a
     step has *no* machine energy profile (e.g. Cotton Farming, Ginning,
     Packaging), a kWh/kg proxy emits a low-confidence activity row — this
     implements the rule "if no machines used, find probable carbon for the
     process" so steps aren't silently zero.
   - **chemical embodied emissions** from `emission_factors.csv` (Chemical rows).
   - **transport emissions**: each step's `transport_leg_after` → mode +
     distance (from `transport_routes.csv`, default export haul otherwise) →
     ton-km × per-mode factor.
6. `machine_workflow.recommend_workflow` — dynamic per-name machine workflow
   from `machine_recommender` (resolves machines even for products outside the
   static routes). Added as `dynamic_workflow` + an `INF-RUN-DYNAMIC-WORKFLOW`
   inference-trace record.
7. `reporting.build_report` — assembles product/confidence/route/impact/
   impact_breakdown/process/machine/activity/chemical/passport blocks.
8. `inference_engine.build_inference_trace` — the audit trail of inference
   records (classification, template, route, machine/resource, emissions,
   + dynamic workflow).
9. `persistence.store_run` — writes the run to PostgreSQL (via `DATABASE_URL`)
   or SQLite/CSV fallback. `GET /api/inference-records` reads recent runs back.

## Other endpoints

- `GET /api/health`, `/api/catalog`, `/api/master-domains`,
  `/api/knowledge-graph/schema`
- `GET /api/workflow?product_name=...` — raw dynamic machine workflow for any name
- `GET /api/inference-records?limit=N` — recent persisted runs
- `GET /api/machine-intelligence`,
  `POST /api/machine-spec-extract` (regex brochure spec extraction)

## Run it

```bash
# backend
cd backend
python3 -m venv .venv && .venv/bin/pip install -r requirements.txt
.venv/bin/uvicorn app.main:app --host 127.0.0.1 --port 8000

# frontend (another shell)
cd frontend && npm install && npm run dev   # http://127.0.0.1:5173
```

Smoke test the pipeline:
```bash
cd backend && .venv/bin/python -c "
from app.services.document_intelligence import extract_document_signals
from app.services.product_intelligence import classify_product, match_template
from app.services.manufacturing_reconstruction import reconstruct_route
from app.services.resource_models import estimate_resources
from app.services.reporting import build_report
sig = extract_document_signals('cotton tee', [], bom_components=[{'material':'cotton','percent':100,'weight_g':215,'origin':'India'}], declared_origin='India')
cls = classify_product(sig); tm = match_template(str(cls['taxonomy']['taxonomy_id']), sig)
route = reconstruct_route(str(tm['template']['default_route_id']))
res = estimate_resources(route['steps'], int(tm['resolved_weight_g']))
print(build_report(cls, tm, route, res)['impact'])
"
```

HTTP round-trip:
```bash
curl -F 'product_description=cotton tee' \
  -F 'bom={"components":[{"material":"cotton","percent":100,"weight_g":215,"origin":"India"}]}' \
  -F 'origin=India' http://127.0.0.1:8000/api/analyze | python3 -m json.tool
```

## Confidence framework (see docs/Architecture.md)

Level 1 Primary (95–99%) → L2 Supplier (80–95%) → L3 Trade (70–85%) →
L4 Industry Avg (50–75%) → L5 Fallback (25–50%). Every master row carries
`version/source/approval_status/confidence`; every activity row carries its
`confidence` label.

## Status & next milestone

Phase 1+2 (knowledge graph, route library, basic inference) were the starting
point. This working session added: structured BOM + real document parsing,
dynamic per-name machine inference, transport/chemical/yield emissions +
mass-balance, the process-level carbon fallback, and PostgreSQL/SQLite
persistence.

**Next per the roadmap:** Step 4 — the *real* brochure→power→carbon path for
apparel machines: fetch authentic brochures (Thies iMaster H2O, Mayer & Cie
Relanit, Rieter G 38, Juki DDL-8700), extract true power/consumables via the
existing PDF extractor (`machine_intelligence.py` /
`machine_analyzer/app.py`), write real kWh-per-unit back into
`machine_energy_profiles.csv`, and let those flow through `estimate_resources`
to replace the industry-average proxies with near-exact figures. Material
origin reconstruction is Phase 2 (Phase 1 carries only tentative origin).

## Step 4 / 4b: near-exact energy from authentic sources

The pipeline resolves each process step's machine **by region**
(`factory_machine_map` × country → most-commonly-installed model; see
`resource_models._rank_models_by_region`), then turns authentic public data
into a per-unit energy figure (`kWh/kg = installed_power / throughput`):

- `brochure_pipeline.py` — explicit, reviewed path:
  `fetch_brochure_text(url)` → `extract_brochure(...)` (review-only candidate
  + derivation) → `promote_energy_profile(...)` (the only call that writes the
  `machine_energy_profiles.csv` master, stamped `Brochure Approved` conf 0.8).
  Governance: extraction is source evidence, never auto-written from runtime.
- `brochure_discovery.py` — live path at `analyze` time, authority ladder:
  DB-approved cache hit (instant, no network) → manufacturer brochure PDF →
  data sheets / O&M / FAT → `site:.gov` (EPREL / DOE / ENERGY STAR) → open LCA
  (EPA AP-42 / openLCA Nexus). Stdlib only (urllib + pdfplumber); precise
  `filetype:pdf "specification sheet"` / `"power consumption" "cycle time"` /
  `site:.gov` search strings bypass marketing pages. Hard `_TOTAL_TIMEOUT`
  wall-clock + per-request machine cap so analyze never hangs on a flaky
  source; every failure degrades to the KG proxy.
- Endpoints: `POST /api/brochure-review`, `POST /api/brochure-fetch`,
  `POST /api/brochure-promote`, and `enrich_machines=true` on `/api/analyze`
  (default off). The analyze response's `brochure_enrichment` block flags each
  machine as KG-proxy / DB-approved / brochure-derived-approximate with the
  derivation basis, so the UI shows approximated results now and a reviewer
  can correct/promote later.

