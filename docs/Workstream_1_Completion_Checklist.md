# Workstream 1 Completion Checklist

## Baseline and Compatibility

- [x] Frozen Apparel baseline tag: `phase1-apparel-baseline`.
- [x] Public API behavior retained; empty `domain` continues to resolve Apparel.
- [x] Unknown named API domains fail explicitly rather than returning Apparel.
- [x] Golden Apparel fixtures captured and used as a mandatory regression gate.

## Domain Boundary

- [x] `app/core` contains contracts, registry, and generic carbon dispatch only.
- [x] `app/core` has no direct `domain_packs.apparel` import.
- [x] Material aliases and parsing vocabulary live in the Apparel pack.
- [x] Apparel classification/template matching dispatch through `ProductIntelligence`.
- [x] Apparel route/origin resolution dispatches through `RouteResolver`.
- [x] Apparel reporting dispatches through `ReportBuilder`.
- [x] Apparel carbon calculation dispatches through `CarbonModel`.
- [x] Built-in packs register at the explicit bootstrap boundary.

## Validation Evidence

- [x] Core-boundary sentinel test detects Apparel facts or concrete-pack imports.
- [x] Generic dispatch contract tests exercise injected pack implementations.
- [x] Full backend test suite passes.
- [x] Golden Apparel snapshot is byte-identical.
- [x] Core/services/domain-pack Python modules compile.
- [x] Frontend TypeScript API consumer compiles.

## Completion Definition

Workstream 1 is complete when the validation evidence above is green in CI for
the committed change set. The next workstream may add a Footwear pack, but may
not alter a core interface or Apparel output without a new approved baseline.
