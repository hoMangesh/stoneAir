# Architecture V2: Manufacturing Intelligence Platform

## Product Principles

1. Everything is traceable.
2. All emissions originate from activity data.
3. Inference results are stored separately from source data.
4. Confidence is a first-class attribute.
5. The Knowledge Graph drives inference.

## Master Domains

The platform is organized around 12 enterprise master domains:

- Product Master
- Material Master
- Process Master
- Machine Master
- Machine Model Master
- Consumable Master
- Chemical Master
- Country Master
- Supplier Master
- Factory Master
- Transport Master
- Emission Factor Master

Supporting operational domains:

- Product Template
- Material Provenance
- Manufacturing Route
- Route Process
- Process Step
- Machine Energy Profile
- Factory Machine Map
- Yield Model
- Carbon Calculation
- Inference Record

## Data Storage Contract

Master and source records live under `data/masters/`.

Runtime calculation and inference records are stored separately:

- `data/calculations/carbon_calculations.csv`
- `data/inference/inference_records.csv`

Every master dataset supports audit fields:

- `version`
- `effective_date`
- `expiry_date`
- `source`
- `approval_status`
- `confidence`

## API Surface

Implemented endpoints:

- `GET /api/health`
- `GET /api/catalog`
- `GET /api/master-domains`
- `GET /api/knowledge-graph/schema`
- `POST /api/analyze`

`POST /api/analyze` returns:

- source document signals
- product taxonomy and template match
- route reconstruction
- process breakdown
- machine model energy breakdown
- activity-data trace
- chemical inventory
- carbon, water, and energy totals
- confidence framework labels
- digital product passport summary

## Knowledge Graph Schema

Nodes:

- Product
- Material
- Route
- Process
- ProcessStep
- MachineCategory
- MachineModel
- Consumable
- Chemical
- Supplier
- Factory
- Country
- Transport
- EmissionFactor

Relationships:

- Product CONTAINS Material
- Material FOLLOWS Route
- Route HAS_PROCESS Process
- Process HAS_STEP ProcessStep
- Process USES MachineCategory
- MachineCategory HAS_MODEL MachineModel
- MachineModel CONSUMES Consumable
- Factory OWNS MachineModel
- Country HAS EmissionFactor
- Transport USES EmissionFactor

## Confidence Framework

- Level 1: Primary Data, 95-99%
- Level 2: Supplier Data, 80-95%
- Level 3: Trade Data, 70-85%
- Level 4: Industry Average, 50-75%
- Level 5: Fallback Logic, 25-50%

## Machine Energy Strategy

Machine energy reconstruction is modeled through:

- `Machine_Category`
- `Machine_Model`
- `Machine_Energy_Profile`
- `Factory_Machine_Map`

The current seed includes representative machine models:

- Thies iMaster H2O
- Mayer & Cie Relanit
- Rieter G 38
- Juki DDL-8700

Their energy profiles currently use KG V2 proxy values and are marked `Pending Brochure Review`.
Public brochures and datasheets should be attached before these records are promoted to supplier or primary-data confidence levels.
