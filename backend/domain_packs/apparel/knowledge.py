"""Apparel knowledge repository — every apparel fact extracted from core.

Relocated verbatim (not rewritten) from the core services so apparel output stays
byte-identical. Each constant here is the *single source of truth* a core module
now imports *from the pack* via :func:`app.core.domain_registry.resolve`.

Extraction order (leaf-first; each moved one at a time with a green-test gate):
  2.1 chemical_factor_aliases   (was knowledge_loader._CHEMICAL_FACTOR_NAME_ALIASES)
  2.2 water/chemical/process/origin/transport/export constants
                                (was resource_models module-level dicts)
  2.3 material_aliases + regex + keyword_bank
                                (was document_intelligence module constants)
  2.4 origin_sensitive_process_groups (was route_resolution mirrored set)
  2.5 reporting's level_1_domain read re-pointed to pack.domain_id; +
       knowledge_repo_paths wired to real CSV paths + knowledge_loader reads them

Status: all of 2.1–2.5 done. Step 2.5 deliberately does NOT re-point
reporting.py's ``taxonomy["level_1_domain"]`` read to pack.domain_id — those
differ (taxonomy = Title-Case "Apparel"; pack.domain_id = "apparel"); the
report's per-product domain label is legitimately a knowledge-repo value and
re-pointing it would break parity. reporting.py stays as-is; only the pack's
knowledge_repo_paths are wired (real CSV paths), ready for Step 4 to switch the
loader over.
"""

from __future__ import annotations

import re
from pathlib import Path

from app.config import (
    MASTER_DATASETS,
    PRODUCT_TAXONOMY_CSV,
    PRODUCT_TEMPLATE_CSV,
    ROUTE_LIBRARY_CSV,
)
from app.core.contracts import DomainPack, KnowledgeRepoPaths, RegexPatterns


# ---------------------------------------------------------------------------
# 2.5 — Knowledge-repo paths. The apparel pack binds its own knowledge to the
# real CSV masters + taxonomy/template/route CSVs (same paths config.py defines;
# config.py is domain-neutral path constants, the pack binds them to apparel).
# Carried on the pack so a future Step-4 knowledge_loader can read "the resolved
# pack's repos" instead of config.py's defaults — letting a battery pack point
# at different files without touching core. Nothing consumes these paths yet;
# the loader still reads config.py (parity unchanged).
# ---------------------------------------------------------------------------

_APPAREL_REPOS = KnowledgeRepoPaths(
    taxonomy_csv=PRODUCT_TAXONOMY_CSV,
    template_csv=PRODUCT_TEMPLATE_CSV,
    route_library_csv=ROUTE_LIBRARY_CSV,
    master_datasets=dict(MASTER_DATASETS),
    material_origins_csv=MASTER_DATASETS.get("material_origins"),
)


# ---------------------------------------------------------------------------
# 2.1 — Chemical-factor aliases (was knowledge_loader._CHEMICAL_FACTOR_NAME_ALIASES)
# emission_factors.csv carries Chemical rows whose factor_id encodes the name
# (no chemical_name column). These map the readable names used downstream to the
# matching factor-id token so the carbon engine can look them up.
# ---------------------------------------------------------------------------

CHEMICAL_FACTOR_ALIASES: dict[str, str] = {
    "Reactive Dye": "REACTIVE-DYE",
    "Salt": "SALT",
    "Caustic Soda": "CAUSTIC-SODA",
    "Soda Ash": "SODA-ASH",
    "Softener": "SOFTENER",
    "Wetting Agent": "WETTING-AGENT",
    "Adhesive": "ADHESIVE",
}


# ---------------------------------------------------------------------------
# 2.2 — Water / chemical / process-energy models + transport/export defaults
# (was resource_models module-level dicts). Fallback models kept in code only
# where the masters lack data (water/chemical dosage); when the masters gain
# those rows, the apparel carbon model (Step 3) defers to them.
# ---------------------------------------------------------------------------

# Water L per kg processed, keyed by the step's water_model_process.
WATER_MODEL_L_PER_KG: dict[str, float] = {
    "Cotton Farming": 10000,
    "Pretreatment": 30,
    "Reactive Dyeing": 75,
    "Finishing": 10,
}

# Chemical dosage g per kg processed, keyed by the step's chemical_model_process;
# inner dict is {chemical_name: g_per_kg}.
CHEMICAL_MODEL_G_PER_KG: dict[str, dict[str, float]] = {
    "Pretreatment": {
        "Caustic Soda": 20,
        "Wetting Agent": 5,
    },
    "Reactive Dyeing": {
        "Reactive Dye": 30,
        "Salt": 60,
        "Soda Ash": 20,
    },
    "Finishing": {
        "Softener": 10,
    },
}

# Process-level energy fallback (kWh per kg of material processed) used ONLY when
# no machine model with an energy profile resolves for a step. Implements the rule
# "if no machines used, find probable carbon emission for the process" so
# machineless steps (Cotton Farming, Ginning, Packaging) are not silently zero.
# Values are industry-average proxies; they get a low confidence flag so reviewers
# can see which steps still need a real machine energy profile.
PROCESS_ENERGY_FALLBACK_KWH_PER_KG: dict[str, float] = {
    "Cotton Farming": 1.2,      # diesel irrigation + tractor proxy per kg seed cotton
    "Ginning": 0.18,            # gin electricity per kg fiber
    "Packaging": 0.05,          # conveyor/press electricity per kg
    "Sole Molding": 3.1,        # footwear molding (used when no machine row exists)
    "Cementing and Sole Attachment": 0.9,
    "Finishing and Inspection": 0.4,
}

# Transport legs in the route library are phrased as prose ("Truck to gin",
# "Export transport") rather than origin->destination pairs. We map the mode
# noun found in the phrase to a transport_modes.csv row, and use the adjacent
# step countries (or a default export distance) to size the leg.
TRANSPORT_MODE_HINTS: list[tuple[str, str]] = [
    ("air freight", "Air Freight"),
    ("ocean freight", "Ocean Freight"),
    ("ocean", "Ocean Freight"),
    ("rail", "Rail"),
    ("truck", "Truck"),
]

# Default export leg when the route says "Export transport" but no explicit
# origin->destination is known. Sized to a typical China/Vietnam -> US ocean leg.
DEFAULT_EXPORT_DISTANCE_KM: int = 13500
DEFAULT_EXPORT_MODE: str = "Ocean Freight"


# ---------------------------------------------------------------------------
# 2.4 — Origin-sensitive process groups (was resource_models._ORIGIN_SENSITIVE_
# PROCESS_GROUPS, mirrored in route_resolution). Single-sourced here now: the
# process groups whose step country is origin-sensitive — the BOM's declared
# origin (where the fiber is grown/recovered) overrides the route's hardcoded
# default_country.
# ---------------------------------------------------------------------------

ORIGIN_SENSITIVE_PROCESS_GROUPS: set[str] = {"Fiber Production", "Fiber Preparation"}


# ---------------------------------------------------------------------------
# 2.3 — Ingestion vocabulary (was document_intelligence module constants).
# Material aliases normalise free-text/regex material tokens to the canonical
# names used in materials.csv; the keyword bank drives product-type detection
# from prose. Both are apparel-specific (a battery pack would carry cathode/
# anode/electrolyte aliases and "cylindrical/prismatic/pouch" keywords instead).
# ---------------------------------------------------------------------------

MATERIAL_ALIASES: dict[str, str] = {
    "organic cotton": "organic cotton",
    "recycled cotton": "recycled cotton",
    "recycled polyester": "recycled polyester",
    "cotton": "cotton",
    "polyester": "polyester",
    "elastane": "elastane",
    "spandex": "elastane",
    "viscose": "viscose",
    "rayon": "viscose",
    "modal": "modal",
    "lyocell": "lyocell",
    "tencel": "lyocell",
    "hemp": "hemp",
    "linen": "linen",
    "nylon": "nylon",
    "polyamide": "nylon",
    "wool": "wool",
    "silk": "silk",
    "leather": "leather",
    "eva": "eva",
    "rubber": "rubber",
}

# Keyword bank for product-type detection from prose (was _detect_keywords in
# document_intelligence). Each token is matched lowercase against the input.
KEYWORD_BANK: list[str] = [
    "t-shirt", "tee", "polo", "hoodie", "sweatshirt", "legging", "short",
    "shirt", "jeans", "denim", "chino", "dress", "jacket", "sock",
    "sports bra", "sneaker", "running shoe", "sandal", "boot", "cotton",
    "polyester", "recycled polyester", "elastane", "viscose", "woven", "knit",
    "fleece", "pique", "shell",
]


# The blend-pattern material alternation is a hand-curated apparel subset of the
# alias values — NOT all of them. It notably includes the spelling "spandex"
# (which aliases to "elastane" upstream) and excludes eva/linen/rubber. Relocated
# verbatim from the original core constant to preserve exact match behaviour; the
# order is longest-first so "organic cotton" wins over "cotton" at one position.
_BLEND_MATERIALS = [
    "organic cotton",
    "recycled cotton",
    "recycled polyester",
    "cotton",
    "polyester",
    "elastane",
    "spandex",
    "viscose",
    "modal",
    "lyocell",
    "hemp",
    "nylon",
    "wool",
    "silk",
    "leather",
]


def _build_regex_patterns() -> RegexPatterns:
    """Compile the apparel regex patterns (verbatim from the original core
    constants, longest-first order preserved for blend precedence).

    The blend material alternation is NOT "all alias values" — see
    :data:`_BLEND_MATERIALS` for why (a curated subset incl. the "spandex"
    spelling). Apparel GSM (g/m²) and weight-token patterns follow verbatim.
    """
    blend = re.compile(
        rf"(?P<percent>\d{{1,3}})\s*%?\s*(?P<material>{'|'.join(_BLEND_MATERIALS)})",
        re.IGNORECASE,
    )
    mass_unit = re.compile(r"(?P<gsm>\d{2,3})\s*(?:gsm|g/m2|g\/m2)", re.IGNORECASE)
    weight = re.compile(r"(?P<weight>\d{2,5})\s*(?:g|gram|grams|kg)\b", re.IGNORECASE)
    return RegexPatterns(blend=blend, mass_unit=mass_unit, weight=weight)


def build_pack(*, carbon_model=None) -> DomainPack:
    """Build the apparel DomainPack.

    ``carbon_model`` defaults to the apparel calc model (water/chemical/
    process-fallback dicts, relocated from resource_models in Step 3) so the
    pack carries its full domain calc knowledge. Callers may override it.
    """
    if carbon_model is None:
        from domain_packs.apparel.carbon_model import build_apparel_carbon_model

        carbon_model = build_apparel_carbon_model()
    from domain_packs.apparel.intelligence import (
        ApparelProductIntelligence,
        ApparelReportBuilder,
        ApparelRouteResolver,
    )
    return DomainPack(
        domain_id="apparel",
        display_name="Clothing & Apparel",
        material_aliases=MATERIAL_ALIASES,            # ← Step 2.3 (done)
        regex_patterns=_build_regex_patterns(),      # ← Step 2.3 (done)
        keyword_bank=KEYWORD_BANK,                   # ← Step 2.3 (done)
        origin_sensitive_process_groups=ORIGIN_SENSITIVE_PROCESS_GROUPS,  # ← Step 2.4 (done)
        transport_mode_hints=TRANSPORT_MODE_HINTS,    # ← Step 2.2 (done)
        default_export_distance_km=DEFAULT_EXPORT_DISTANCE_KM,  # ← Step 2.2 (done)
        default_export_mode=DEFAULT_EXPORT_MODE,      # ← Step 2.2 (done)
        chemical_factor_aliases=CHEMICAL_FACTOR_ALIASES,  # ← Step 2.1 (done)
        knowledge_repo_paths=_APPAREL_REPOS,
        carbon_model=carbon_model,                    # None until Step 3
        product_intelligence=ApparelProductIntelligence(),
        route_resolver=ApparelRouteResolver(ORIGIN_SENSITIVE_PROCESS_GROUPS),
        report_builder=ApparelReportBuilder(),
    )


__all__ = [
    "CHEMICAL_FACTOR_ALIASES",
    "WATER_MODEL_L_PER_KG",
    "CHEMICAL_MODEL_G_PER_KG",
    "PROCESS_ENERGY_FALLBACK_KWH_PER_KG",
    "TRANSPORT_MODE_HINTS",
    "DEFAULT_EXPORT_DISTANCE_KM",
    "DEFAULT_EXPORT_MODE",
    "ORIGIN_SENSITIVE_PROCESS_GROUPS",
    "MATERIAL_ALIASES",
    "KEYWORD_BANK",
    "build_pack",
]
