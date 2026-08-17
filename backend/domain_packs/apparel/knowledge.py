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

Status: 2.1 done; 2.2–2.5 land in subsequent commits (scaffold in place so the
pack builds even while those constants still live in core — core and pack hold
the same values until each relocate lands).
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


def build_pack(*, carbon_model=None) -> DomainPack:
    """Build the apparel DomainPack. ``carbon_model`` is supplied in Step 3."""
    return DomainPack(
        domain_id="apparel",
        display_name="Clothing & Apparel",
        material_aliases={},                           # wired in Step 2.3
        regex_patterns=RegexPatterns(None, None, None),  # wired in Step 2.3
        keyword_bank=[],                              # wired in Step 2.3
        origin_sensitive_process_groups=set(),        # wired in Step 2.4
        transport_mode_hints=[],                      # wired in Step 2.2
        default_export_distance_km=13500,             # wired in Step 2.2 (verbatim)
        default_export_mode="Ocean Freight",          # wired in Step 2.2 (verbatim)
        chemical_factor_aliases=CHEMICAL_FACTOR_ALIASES,  # ← Step 2.1 (done)
        knowledge_repo_paths=_APPAREL_REPOS,
        carbon_model=carbon_model,                    # None until Step 3
    )


__all__ = ["CHEMICAL_FACTOR_ALIASES", "build_pack"]
