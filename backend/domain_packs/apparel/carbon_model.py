"""Apparel carbon-calculation model — the domain-specific calc *model*.

Per the Workstream 1 engine-in-core / rules-in-domain split: the *engine*
(reusable mass-balance + factor×quantity + breakdown + transport machinery) is
core; the *model* owns what makes apparel's carbon distinct — the
machine-kWh×grid path plus its apparel-specific dosage/fallback parameters
(water L/kg, chemical g/kg, process-energy kWh/kg proxies), each keyed by
apparel process names.

Step 3 (minimal scope, this commit) relocates the three apparel calc-model
dicts out of :mod:`app.services.resource_models` to here, so core holds **no
apparel facts at all**. ``estimate_resources`` (core) reads them through the
resolved pack's ``carbon_model`` (``pack.carbon_model.water_model_l_per_kg``
etc.) — the dependency points only inward (core <- bootstrap <- packs), never
core -> a concrete pack.

The deeper engine/model split — a :class:`~app.core.contracts.CarbonModel`
``evaluate(...)`` Protocol plus a generic ``app.core.carbon_engine`` module
that *dispatches* to a model — is deferred to a follow-up. The Protocol is
already declared in :mod:`app.core.contracts`; this module is the natural home
for it once the dispatch lands. For now this is a plain holder the engine
reads attributes from, parity-identical to the prior inline constants.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class ApparelCarbonModel:
    """Holder for apparel calc-model parameters, read by the core engine.

    Implements the ``CarbonModel`` Protocol (``evaluate``) only structurally —
    the full dispatch is deferred; today the engine reads these attributes
    directly through ``pack.carbon_model``. Frozen so a registered model is
    immutable at runtime (governance invariant).
    """

    # Water L per kg processed, keyed by the step's water_model_process.
    # All fallback models kept in code only where the masters lack data
    # (water/chemical dosage); when the masters gain those rows, the engine
    # defers to them.
    water_model_l_per_kg: dict[str, float]

    # Chemical dosage g per kg processed, keyed by the step's
    # chemical_model_process; inner dict is {chemical_name: g_per_kg}.
    chemical_model_g_per_kg: dict[str, dict[str, float]]

    # Process-level energy fallback (kWh per kg of material processed) used ONLY
    # when no machine model with an energy profile resolves for a step. Implements
    # the rule "if no machines used, find probable carbon emission for the
    # process" so machineless steps (Cotton Farming, Ginning, Packaging) are not
    # silently zero. Values are industry-average proxies; low confidence flag.
    process_energy_fallback_kwh_per_kg: dict[str, float]

    def evaluate(self, *, route_steps, weight_g, origin_context=None, repos=None):
        """Placeholder for the future generic-engine dispatch.

        Today the core engine (`estimate_resources`) reads this model's
        attributes directly; a subsequent workstream replaces that with a
        generic ``app.core.carbon_engine`` calling this method. Intentionally
        unused now — defined so the model satisfies the ``CarbonModel``
        Protocol's shape and the contract stays honest.
        """
        raise NotImplementedError(
            "ApparelCarbonModel.evaluate is deferred to the carbon-engine split; "
            "the core engine reads this model's attributes today."
        )


def build_apparel_carbon_model() -> ApparelCarbonModel:
    """Construct the apparel carbon model from the verbatim relocated dicts.

    Relocated verbatim from :mod:`app.services.resource_models` (was module-level
    ``WATER_MODEL_L_PER_KG`` / ``CHEMICAL_MODEL_G_PER_KG`` /
    ``PROCESS_ENERGY_FALLBACK_KWH_PER_KG``) so apparel output stays byte-identical.
    """
    return ApparelCarbonModel(
        water_model_l_per_kg={
            "Cotton Farming": 10000,
            "Pretreatment": 30,
            "Reactive Dyeing": 75,
            "Finishing": 10,
        },
        chemical_model_g_per_kg={
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
        },
        process_energy_fallback_kwh_per_kg={
            "Cotton Farming": 1.2,      # diesel irrigation + tractor proxy / kg seed cotton
            "Ginning": 0.18,            # gin electricity / kg fiber
            "Packaging": 0.05,          # conveyor/press electricity / kg
            "Sole Molding": 3.1,        # footwear molding (no machine row)
            "Cementing and Sole Attachment": 0.9,
            "Finishing and Inspection": 0.4,
        },
    )


__all__ = ["ApparelCarbonModel", "build_apparel_carbon_model"]
