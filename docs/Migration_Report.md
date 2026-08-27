# Domain-Agnostic Platform Migration Report

## Objective

Evolve the apparel LCA prototype into a plugin-based manufacturing intelligence
platform without a big-bang rewrite, API break, or loss of existing apparel
behaviour.

## Phase Gate Status

| Phase | Gate | Status |
|---|---|---|
| 1 | Freeze apparel baseline, lock public API behavior, capture golden outputs | Complete; golden fixtures live in `backend/tests/_golden/snapshot.json`. Baseline tag is `phase1-apparel-baseline` at the committed pre-migration HEAD. |
| 2 | Publish core-to-domain contracts | Complete: `DomainPack`, `KnowledgeRepoPaths`, `RegexPatterns`, `CarbonModel`. |
| 3 | Extract Apparel knowledge | Complete for aliases, parsing patterns, transport policy, chemical aliases, repositories, and carbon model values. |
| 4 | Refactor core services to contract-only dependencies | Complete for Workstream 1: classification, template matching, route/origin resolution, reporting, and carbon evaluation are service facades over pack interfaces. |
| 5 | Dependency injection/plugin pattern | Complete for built-in packs through `domain_packs.bootstrap` and the registry. |
| 6 | Regression after each extraction | Active gate: golden output, focused unit tests, and core-boundary tests. |
| 7 | Prove zero apparel dependencies in core | Automated source sentinel is included in `test_ws1_core_boundary.py`; it checks core modules for apparel facts and concrete-pack imports. |

## Current Apparel Plugin

`backend/domain_packs/apparel/` owns:

- canonical material aliases, product keywords, and parsing regexes;
- route/origin/transport policy;
- chemical-factor aliases and repository locations;
- apparel water, chemical-dosage, and process-energy fallback rules;
- `ApparelCarbonModel.evaluate()`, which invokes the shared activity-data
  machinery through the stable carbon-model contract.
- `ApparelProductIntelligence`, `ApparelRouteResolver`, and
  `ApparelReportBuilder`, which own Apparel behavior behind the stable product,
  route, and reporting interfaces.

## Regression Rules

Before merging every extraction:

1. Run the frozen apparel snapshot check.
2. Run the full backend test suite.
3. Run the core-boundary test to ensure no concrete apparel dependency leaked
   into core.
4. Compile the frontend TypeScript client if its API contract changed.
5. Treat a changed golden snapshot as a breaking behavior change unless a
   reviewed, documented data/model change explicitly approves it.

## Risks and Controls

| Risk | Control |
|---|---|
| A service retains apparel literals or imports | Core-boundary sentinel and code review rule: `app/core` never imports a pack. |
| A new pack changes apparel outputs | Golden apparel snapshot is a mandatory gate. |
| Contract becomes too apparel-shaped | New domain proposals must satisfy the existing result contract with domain-owned rules; extend contracts additively only. |
| Plugin registration is implicit or hidden | All built-in packs register through explicit `domain_packs.bootstrap`. |
| CSV master assumptions leak across domains | `KnowledgeRepoPaths` is owned by the pack; loader cache is keyed by domain ID. |
| Proxy results are mistaken for primary data | `impact_data_quality`, source tiers, approval status, and brochure-first energy selection are exposed in reports. |

## Next Bounded Step

Create a minimal Footwear domain pack that implements the same interfaces using
Footwear-only knowledge repositories. It must begin with contract tests and
must not alter the frozen Apparel snapshot.
