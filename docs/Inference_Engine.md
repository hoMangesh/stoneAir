# Inference Engine V1

Inference Engine V1 turns document signals and knowledge graph defaults into a traceable LCA estimate.

## Scope

The engine currently produces runtime inference records for:

- Product classification against Product Taxonomy V1
- Product template matching against Product Template Library V1
- Route reconstruction against Route Library V2
- Machine, energy, water, and chemical estimation
- Emission calculation from activity data and emission factors

## Principles

- Source master data remains separate from inferred runtime outputs.
- Every inference record includes input, output, agent, evidence, source, status, version, timestamp, and confidence.
- Confidence is derived from the weakest relevant evidence layer where possible.
- Runtime inference records are returned by the API now and should later persist to PostgreSQL.

## API Surfaces

- `POST /api/analyze` returns the product report plus `inference_trace`.
- `GET /api/inference-records` returns seed inference records from `data/inference/inference_records.csv`.

## Next Persistence Target

Create a PostgreSQL `inference_records` table with the same runtime fields:

- `inference_id`
- `inference_type`
- `input_data`
- `output_data`
- `agent`
- `confidence_score`
- `confidence_label`
- `timestamp`
- `version`
- `source`
- `approval_status`
- `evidence_json`

