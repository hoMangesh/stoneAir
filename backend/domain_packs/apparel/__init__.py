"""Apparel domain pack — extracted knowledge, rules, and calc model for the
Clothing & Apparel industry.

This pack is the first concrete instance of the Workstream 1 core↔domain
contract. It exists to prove the boundary: every apparel fact formerly baked
into core modules (``resource_models``, ``document_intelligence``,
``knowledge_loader``, ``route_resolution``, ``reporting``) relocates here, and
core reaches it only through :class:`app.core.contracts.DomainPack`.

Importing this package materializes the apparel ``DomainPack`` AND registers it
with :mod:`app.core.domain_registry` under id ``"apparel"`` — so the import is
the registration side-effect. Core never imports this module; a runtime
bootstrap (added in Step 4) imports the registered packs so ``resolve('apparel')``
succeeds without core knowing the pack's path.

Contents (filled in across Step 2 sub-steps, leaf-first):
- :mod:`knowledge`    — material aliases, regex patterns, keyword bank,
                        origin-sensitive process groups, transport hints,
                        export defaults, chemical-factor aliases, knowledge-repo
                        paths (all extracted from core verbatim).
- :mod:`carbon_model` — the apparel carbon model (Step 3): machine-kWh×grid +
                        process fallbacks + water/chemical dosage, behind the
                        ``CarbonModel`` Protocol.
"""
from __future__ import annotations

from app.core.contracts import DomainPack
from app.core.domain_registry import register
from domain_packs.apparel.knowledge import build_pack


def _build_and_register() -> DomainPack:
    """Build the apparel pack once and register it under ``"apparel"``.

    A module-level call to this function (below) is the import side-effect: the
    act of importing ``domain_packs.apparel`` makes ``resolve("apparel")``
    work. Kept as a named function so tests/bootstraps can force a rebuild.
    """
    pack = build_pack()
    register(pack.domain_id, lambda: pack)
    return pack


# Import side-effect: apparel is resolvable from the moment this package loads.
pack: DomainPack = _build_and_register()


__all__ = ["pack", "_build_and_register"]
