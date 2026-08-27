# Workstream 4 Migration Report

## Outcome

Workstream 4 adds generic reasoning around the canonical Product Digital Twin. It makes existing inference trace data explainable without moving apparel knowledge into core or changing existing analysis/report calculations.

## Changes

| Area | Implementation | Compatibility result |
| --- | --- | --- |
| Twin lifecycle | Optional `reasoning` section and `reasoned` stage | Existing final-Twin validation unchanged |
| Evidence | Generic projection of existing sources/evidence/confidence | No new knowledge is created |
| Confidence | Conservative weakest-link propagation | Missing confidence remains `null` |
| Gaps | Declarative no-guess records | Proxy machine data requests brochure-backed evidence |
| Rules | Pure deterministic predicates | No domain-pack dependency |
| Explanation | Stateless router plus bounded interpretation | Frozen `/api/analyze` untouched |

## Dependency boundary

`app.core.{evidence_graph,confidence,rules,twin}` and `app.services.{reasoning_engine,gap_detection}` have no import of `domain_packs.apparel`. Domain-specific facts remain resolved through the existing Workstream 1 contracts before they reach the Twin.

## Compatibility and migration strategy

No legacy payload field, classification, route, resource calculation, emission factor, or report builder was changed. Existing pipelines may opt in by calling `ReasoningEngine.enrich(twin)` after trace enrichment. The standalone router supports clients that already hold a serialized Twin and avoids a second mutable store.

## Risks and mitigations

| Risk | Mitigation |
| --- | --- |
| Sparse historic trace data | Reports `uncovered` confidence rather than inventing a score |
| Proxy evidence mistaken for primary data | Explicit gap asks for manufacturer brochure/model/measurement |
| Future LLM overreach | Provider-free bounded layer and documented citation-only contract |
| Router not mounted in frozen app | Independently mountable router preserves the existing API release boundary |

## Recommendation

Accept Workstream 4. In the next non-frozen API release, mount the router and call the engine after inference tracing, then add UI rendering for gaps and evidence citations. Neither step requires importing an apparel pack into core.
