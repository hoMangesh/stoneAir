"""Generic carbon-engine dispatch.

The engine deliberately owns no industry rules.  It resolves a domain pack at
the service boundary and invokes that pack's :class:`CarbonModel` with the
route, mass, origin context, and the already-loaded knowledge repositories.
Each domain model is therefore responsible for turning its activity data into
the common result contract.
"""
from __future__ import annotations

from typing import Any

from app.core.contracts import DomainPack


def evaluate(
    *,
    pack: DomainPack,
    route_steps: list[dict[str, str]],
    weight_g: int,
    origin_context: dict[str, Any] | None,
    repos: Any,
) -> dict[str, Any]:
    """Evaluate a route through the selected domain's carbon model.

    ``repos`` is intentionally opaque to the core: it is the domain's loaded
    knowledge repository, supplied by the service layer.  Keeping the engine
    unaware of CSV schemas lets another domain use a different repository
    implementation without changing this dispatch boundary.
    """
    result = pack.carbon_model.evaluate(
        route_steps=route_steps,
        weight_g=weight_g,
        origin_context=origin_context,
        repos=repos,
    )
    required = {
        "totals",
        "process_breakdown",
        "machine_breakdown",
        "activity_trace",
        "chemical_inventory",
    }
    missing = required.difference(result)
    if missing:
        raise ValueError(
            f"carbon model for domain {pack.domain_id!r} returned an incomplete result: "
            f"missing {sorted(missing)}"
        )
    return result


__all__ = ["evaluate"]
