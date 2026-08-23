"""Core ↔ domain-pack contracts (the Workstream 1 boundary).

Everything industry-specific — material lexicons, regex patterns, origin-sensitive
process groups, transport hints, knowledge-repo paths, and the carbon-calculation
*model* — is exposed to core through these types. Core depends only on
:class:`DomainPack`; it never imports a concrete pack directly. This is the
load-bearing boundary of the "core never changes per industry" guarantee.

The contract intentionally encodes the apparel constants **as they exist today**
so the apparel pack can hold them verbatim and apparel output stays byte-identical.
No behaviour change happens here — this module defines types only; wiring happens
in later steps.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Protocol, runtime_checkable


# ---------------------------------------------------------------------------
# Regex + knowledge-repo path value-objects
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class RegexPatterns:
    """Domain-specific regex compiled patterns, carried by a pack.

    Apparel uses blend/GSM/weight patterns; a battery pack would carry
    chemistry/capacity/voltage patterns instead. Kept as compiled ``re.Pattern``
    so callers use them directly (embedding the regex source in the pack makes
    the domain's parsing vocabulary inspectable in one place).
    """

    blend: re.Pattern[str] | None
    mass_unit: re.Pattern[str] | None          # apparel: GSM (g/m²); batteries may omit
    weight: re.Pattern[str] | None


@dataclass(frozen=True)
class KnowledgeRepoPaths:
    """Filesystem paths to a domain's versioned knowledge repositories.

    Today these are the apparel master CSVs (``data/masters/*.csv`` + the
    taxonomy/template/route CSVs). True per-repo versioning discipline is
    Workstream 3; here the core only needs to know *where a pack's knowledge
    lives* rather than hardcoding apparel paths in ``config.py``. A pack owns
    its own repo root so two domains never collide on the same files.
    """

    taxonomy_csv: Path
    template_csv: Path
    route_library_csv: Path
    master_datasets: dict[str, Path] = field(default_factory=dict)
    # Per-material origin provenance root (optional; apparel uses material_origins.csv).
    material_origins_csv: Path | None = None


# ---------------------------------------------------------------------------
# Carbon-model protocol — the domain-specific calc *model*
# ---------------------------------------------------------------------------


@runtime_checkable
class CarbonModel(Protocol):
    """The domain's carbon-calculation model, dispatched by the generic engine.

    Workstream 1's engine-in-core / rules-in-domain split: the *engine* in
    ``app.core.carbon_engine`` owns reusable machinery (mass-balance walk,
    factor×quantity aggregation, activity-row construction, breakdown,
    confidence/``source_tier`` propagation). The *model* owns what makes a
    domain's carbon distinct — apparel: machine-kWh×grid + process fallbacks +
    water/chemical dosage; battery (later): composition×embodied-emission-factor.

    The engine calls ``pack.carbon_model.evaluate(...)`` and the model returns a
    fully-formed activity trace + totals the engine aggregates; the engine does
    not know whether carbon came from machines or material composition. This
    contract is the seam a new industry plugs into without touching core.

    NOTE: this Protocol is declared in WS1 for the boundary; full extraction of
    ``estimate_resources`` into an engine + apparel model happens in Step 3.
    The signature below is the intended shape; callers do not invoke it yet.
    """

    def evaluate(
        self,
        *,
        route_steps: list[dict[str, str]],
        weight_g: int,
        origin_context: dict[str, Any] | None = None,
        repos: Any = None,
    ) -> dict[str, Any]:
        """Return ``{"totals": ..., "activity_trace": [...], "machine_breakdown": [...],
        "process_breakdown": [...], "chemical_inventory": {...}}``.

        Implementations must source every factor/material/machine from ``repos``
        (the resolved pack's loaded knowledge) and emit ``confidence`` via
        :func:`app.services.knowledge_loader.confidence_level` so the engine's
        aggregation stays domain-neutral.
        """
        ...


@runtime_checkable
class ProductIntelligence(Protocol):
    """Classify a domain product and match it to a domain template."""

    def classify(self, *, signals: Any, repos: Any = None) -> dict[str, Any]: ...
    def match_template(self, *, taxonomy_id: str, signals: Any, repos: Any = None) -> dict[str, Any]: ...


@runtime_checkable
class RouteResolver(Protocol):
    """Resolve a domain route and the origin context required to evaluate it."""

    def resolve(self, *, taxonomy_id: str, signals: Any, default_route_id: str | None, repos: Any = None) -> dict[str, Any]: ...
    def resolve_origin_context(self, *, signals: Any, repos: Any = None) -> dict[str, Any] | None: ...


@runtime_checkable
class ReportBuilder(Protocol):
    """Build the public report shape for a domain analysis."""

    def build(self, *, classification: dict[str, Any], template_match: dict[str, Any], route: dict[str, Any], resources: dict[str, Any]) -> dict[str, Any]: ...


# ---------------------------------------------------------------------------
# DomainPack — the one contract core depends on
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class DomainPack:
    """A self-contained industry plug-in: its knowledge + rules + calc model.

    Core resolves a pack by ``domain_id`` (:mod:`app.core.domain_registry`) and
    reaches all domain-specific behaviour through this object. Adding an
    industry means authoring a new ``DomainPack`` + registering it; core is
    untouched. Every field here corresponds to an apparel constant that today
    lives in a core module and is being relocated to the pack in Step 2.

    Fields are frozen so a pack is registered once and cannot be mutated at
    runtime (a governance invariant: who-writes-what-when stays explicit).
    """

    domain_id: str                       # "apparel", "ev_battery" — matches taxonomy level_1_domain / industries.json
    display_name: str                    # "Clothing & Apparel" — for reports/traces, not for filtering

    # Ingestion vocabulary (was document_intelligence module-level constants):
    material_aliases: dict[str, str]     # was MATERIAL_ALIASES
    regex_patterns: RegexPatterns        # was BLEND/GSM/WEIGHT_PATTERN
    keyword_bank: list[str]             # was _detect_keywords keyword bank

    # Reasoning/calc parameters (were resource_models / knowledge_loader constants):
    origin_sensitive_process_groups: set[str]           # was _ORIGIN_SENSITIVE_PROCESS_GROUPS
    transport_mode_hints: list[tuple[str, str]]         # was _TRANSPORT_MODE_HINTS
    default_export_distance_km: int                      # was DEFAULT_EXPORT_DISTANCE_KM
    default_export_mode: str                            # was DEFAULT_EXPORT_MODE
    chemical_factor_aliases: dict[str, str]             # was knowledge_loader._CHEMICAL_FACTOR_NAME_ALIASES

    # Knowledge stores + calc model:
    knowledge_repo_paths: KnowledgeRepoPaths
    carbon_model: CarbonModel
    product_intelligence: ProductIntelligence
    route_resolver: RouteResolver
    report_builder: ReportBuilder


__all__ = [
    "RegexPatterns",
    "KnowledgeRepoPaths",
    "CarbonModel",
    "ProductIntelligence",
    "RouteResolver",
    "ReportBuilder",
    "DomainPack",
]
