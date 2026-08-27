# Workstream 1 Acceptance Report

**Status: PASS**  
**Acceptance baseline:** `phase1-apparel-baseline`  
**Completed commits:** `6327f27`, `077e895`, `bdddd51`

## Scope Accepted

Workstream 1 establishes a domain-agnostic manufacturing-intelligence core
without changing the Apparel model's frozen behavior.

- Core publishes and uses four pack interfaces: `ProductIntelligence`,
  `RouteResolver`, `ReportBuilder`, and `CarbonModel`.
- The Apparel pack owns Apparel classification, template matching, route/origin
  resolution, report shaping, parsing vocabulary, and carbon rules.
- The activated Dummy pack implements all four interfaces with self-contained
  synthetic behavior, proving that bootstrap and the core do not require
  Apparel-specific code paths.
- FastAPI bootstraps installed packs once at startup.
- Upload I/O is asynchronous at the FastAPI boundary; document parsing is a
  synchronous raw-byte service operation.

## Acceptance Evidence

| Check | Result |
|---|---|
| Full backend regression suite | **PASS - 107 tests passed** |
| Apparel golden output | **PASS - byte-identical** |
| Core/service/domain-pack compilation | **PASS** |
| Core concrete-Apparel import scan | **PASS - none found** |
| Frontend TypeScript check | **PASS** |
| Activated Dummy pack bootstrap | **PASS - `apparel`, `dummy` registered** |
| Real FastAPI multipart PDF analysis | **PASS - HTTP 200** |

## End-to-End BOM Regression Reference

The supplied hypothetical Levi's-style denim-trouser BOM PDF was submitted to
the booted local API through `POST /api/analyze` with `domain=apparel`.

| Output | Observed result |
|---|---|
| Matched template | `Five-Pocket Denim Jean` |
| Route | `ROUTE-APP-WVN-DENIM-001` |
| Process rows / activity rows | 11 / 17 |
| Carbon footprint | 3.014 kgCO2e |
| Energy / water | 4.616 kWh / 8842.959 L |
| Overall confidence | Level 4 - Industry Average |
| Quality labels | Energy proxy; modelled-water proxy; chemical-factor proxy; freight proxy |

The run completed without the prior un-awaited `UploadFile.read()` / `seek()`
warnings. Its document signals included `jeans`, `denim`, `cotton`,
`polyester`, and `woven`, and it correctly followed the Denim Jean route.

## Risks and Non-Blocking Limitations

1. PDF tables currently contribute text/keywords but are not yet mapped into a
   structured component-level BOM. This is a document-intelligence enhancement,
   not a Workstream 1 core coupling.
2. The Dummy pack is an activated contract-validation plugin, not a user-facing
   product domain. Production deployment should expose only intended domains in
   UI/API capability discovery.
3. Current impact values retain their explicit proxy labels until reviewed
   supplier, meter, logistics, and manufacturer-brochure evidence replaces
   those master records.
4. Built-in plugin registration is explicit and static. Dynamic third-party
   pack discovery, signing, and lifecycle governance are a later platform
   concern.

## Recommendation

**Accept Workstream 1 and begin Workstream 2.** The next bounded task should
create a minimal Footwear pack with isolated knowledge repositories and the
same four interfaces. Keep the Apparel golden snapshot mandatory and do not
promote the Dummy pack beyond contract-validation use.
