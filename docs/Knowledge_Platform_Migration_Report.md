# Generic Knowledge Platform Migration Report

## Scope

Implement a domain-neutral knowledge governance layer while Workstreams 1 and 2
remain frozen. The platform must normalize master records, verify provenance,
and expose confidence without changing domain knowledge or LCA calculation
behavior.

## Completed Sub-Phases

| Phase | Commit | Result |
|---|---|---|
| Canonical contracts and read-only repository | `93fb4cc` | Added `KnowledgeEntity`, `Evidence`, `KnowledgeRepository`, and master-data adapter. |
| Verification and confidence pipeline | `48ba630` | Added offline validation, provenance reporting, source/structural confidence scoring. |
| Documentation and acceptance gate | pending final documentation commit | Added entity diagram, repository spec, migration mapping, and checklist. |

## Migration Evidence

The Apparel adapter currently exposes 155 entities:

- 13 materials
- 12 processes
- 52 machines
- 4 suppliers
- 5 geography records
- 52 energy profiles
- 17 emission factors

The offline verification run returned **PASS**: 155 structurally valid records,
0 warnings, 0 errors, and average structural confidence of 0.67.

## Compatibility Guarantee

- The existing `load_master_data` API and indexes are unchanged.
- CSV master values are not rewritten, enriched, or auto-approved.
- The knowledge repository is read-only.
- No calculation service consumes the new repository yet.
- Apparel golden output remains the mandatory behavior gate.

## Risks and Next Step

- The V1 adapter assumes a single master-data shape. Future domains should map
  their repositories intentionally rather than reusing Apparel dataset paths.
- `energy_profile` identity is currently scoped by entity type plus
  `machine_model_id`; a future persistent store should use a composite key.
- Structural confidence is governance completeness, not a scientific quality
  score; reports must retain source tier and approval status.

Next: add optional query/filter and persistence interfaces only after a domain
pack can supply its own master repository map. Keep this verifier read-only and
preserve frozen Workstream 1/2 regression gates.
