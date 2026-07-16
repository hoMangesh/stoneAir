# Machine Intelligence Layer

## Purpose

The Machine Intelligence layer connects process reconstruction to actual machine-level activity data.

It supports:

- machine category mapping
- machine model inference
- public brochure and datasheet tracking
- candidate spec extraction
- machine energy profile governance
- factory capability matching

## Data Contracts

Source/document metadata:

- `data/masters/machine_brochures.csv`

Reviewed extraction candidates:

- `data/masters/machine_spec_extractions.csv`

Machine energy profiles:

- `data/masters/machine_energy_profiles.csv`

Factory installation evidence:

- `data/masters/factory_machine_map.csv`

## Current Implementation

Implemented endpoints:

- `GET /api/machine-intelligence`
- `POST /api/machine-spec-extract`

Implemented frontend workflows:

- Machine brochure repository status table
- Machine spec extraction workbench
- Review-only candidate display for power, throughput, capacity, and liquor ratio

`POST /api/machine-spec-extract` accepts pasted text or an uploaded text-like file and returns candidate values for:

- power
- throughput
- capacity
- liquor ratio

Extraction output is not written into master data automatically. It must be reviewed before promotion into approved source records.

The frontend workbench follows the same rule. It can call the extractor and display candidates, but it does not mutate `data/masters/`.

## Governance Rule

Machine brochure extraction is source evidence, not inference output.

Runtime AI decisions should go to `data/inference/`.
Approved brochure-derived specs should go to `data/masters/machine_spec_extractions.csv`.
Approved machine utility assumptions should go to `data/masters/machine_energy_profiles.csv`.
