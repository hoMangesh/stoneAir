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

Status: 2.1 done; 2.2 + 2.4 done; 2.3 + 2.5 land in subsequent commits
(scaffold in place so the pack builds even while those constants still live in
core — core and pack hold the same values until each relocate lands).
"""

from __future__ import annotations

from pathlib import Path

from app.core.contracts import DomainPack, KnowledgeRepoPaths, RegexPatterns


# ---------------------------------------------------------------------------
# 2.5 (LATER) — Knowledge-repo paths.
# The core engine references no paths; the pack carries its own repo root so two
# domains never collide. Filled in Step 2.5/4 to mirror config.py verbatim; left
# as empty placeholder paths here so the pack builds without wiring.
# ---------------------------------------------------------------------------

_APPAREL_REPOS = KnowledgeRepoPaths(
    taxonomy_csv=Path(""),
    template_csv=Path(""),
    route_library_csv=Path(""),
    master_datasets={},
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


def build_pack(*, carbon_model=None) -> DomainPack:
    """Build the apparel DomainPack. ``carbon_model`` is supplied in Step 3."""
    return DomainPack(
        domain_id="apparel",
        display_name="Clothing & Apparel",
        material_aliases={},                           # wired in Step 2.3
        regex_patterns=RegexPatterns(None, None, None),  # wired in Step 2.3
        keyword_bank=[],                              # wired in Step 2.3
        origin_sensitive_process_groups=ORIGIN_SENSITIVE_PROCESS_GROUPS,  # ← Step 2.4 (done)
        transport_mode_hints=TRANSPORT_MODE_HINTS,    # ← Step 2.2 (done)
        default_export_distance_km=DEFAULT_EXPORT_DISTANCE_KM,  # ← Step 2.2 (done)
        default_export_mode=DEFAULT_EXPORT_MODE,      # ← Step 2.2 (done)
        chemical_factor_aliases=CHEMICAL_FACTOR_ALIASES,  # ← Step 2.1 (done)
        knowledge_repo_paths=_APPAREL_REPOS,
        carbon_model=carbon_model,                    # None until Step 3
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
    "build_pack",
]
