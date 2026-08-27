# Generic Knowledge Platform Completion Checklist

## Canonical Model

- [x] Domain-neutral entities cover material, process, machine, supplier,
  geography, energy profile, and emission factor.
- [x] Every entity carries ID, domain, version, source, evidence, confidence,
  approval state, validity dates, and lossless attributes.
- [x] Repository contract supports get, list, and provenance.

## Apparel Migration

- [x] Existing Apparel masters map read-only into canonical entities.
- [x] Existing IDs, versions, source strings, approval states, and confidence
  values are preserved.
- [x] Existing calculation loader/indexes remain unchanged.

## Verification

- [x] Pipeline verifies identity, version, source, evidence, approval, date,
  and confidence range.
- [x] Pipeline reports provenance and separates source confidence from
  structural confidence.
- [x] Apparel verification passes for 155 canonical entities with no findings.

## Regression Gates

- [x] Focused repository and verification tests pass.
- [x] Full backend suite: 116 tests passed.
- [x] Apparel golden snapshot is byte-identical.
- [x] Core/services/domain-pack modules compile and core has no concrete Apparel import.
- [x] Frontend TypeScript typecheck passed.
- [ ] Documentation commit - final acceptance phase.
