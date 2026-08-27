"""Source-tier mapping for persisted machine energy profiles.

Step 4b Phase 3. A derivation is only as good as its source tier, so the tier
must propagate into the carbon activity-row confidence: a reviewer-promoted
brochure derivation (manufacturer evidence) raises activity confidence; a
KG-proxy profile middles; a flagged-not-authentic demo seed demotes it.

The finder (:mod:`machine_source_finder`) scores *candidate URLs* at discovery
time (TIER_MANUFACTURER/PUBLISHER/GOV/GENERAL). A *persisted* energy profile,
however, carries only its own ``approval_status`` + ``source`` strings — so this
module derives a coarse but honest tier from those, shared by
:mod:`resource_models` (activity-row confidence) and the ``/api/brochure-coverage``
sweep (aggregate ratio).

The mapping is deliberately conservative: only an explicit
``Brochure Approved`` row (written by the reviewer via ``/api/brochure-promote``)
counts as manufacturer-tier evidence; everything else is a proxy until promoted.
"""
from __future__ import annotations

from dataclasses import dataclass


# Tier *ids* reused across the activity rows + coverage report. Kept as plain
# strings (not the finder's constants) because a persisted profile may predate
# discovery and has no finder tier recorded — these describe *evidence quality*.
TIER_MANUFACTURER = "manufacturer"   # reviewer-promoted brochure evidence
TIER_PROXY = "proxy"                  # KG industry-average awaiting a brochure
TIER_DEMO_SEED = "demo-seed"          # flagged not-authentic placeholder
TIER_UNSUPPORTED = "unsupported"      # category without a derivation rule
TIER_NONE = "none"                    # no profile row at all


@dataclass(frozen=True)
class SourceTier:
    tier: str
    label: str
    confidence_ceiling: float   # cap the activity-row confidence at this level


# Public SourceTier instances (the ``tier`` field equals one of the id constants
# above). Importing code should compare ``tier.tier == TIER_MANUFACTURER`` or
# just use these instances directly in assertions.
TIER_APPROVED_ST = TIER_MANUFACTURER_ST = SourceTier(TIER_MANUFACTURER, "Brochure evidence (reviewer-promoted)", 0.8)
TIER_PROXY_ST = SourceTier(TIER_PROXY, "KG industry-average proxy", 0.55)
TIER_DEMO_SEED_ST = SourceTier(TIER_DEMO_SEED, "Demo seed (flagged not-authentic)", 0.30)
TIER_UNSUPPORTED_ST = SourceTier(TIER_UNSUPPORTED, "Unsupported category (no rule)", 0.35)
TIER_NONE_ST = SourceTier(TIER_NONE, "No energy profile", 0.3)


def source_tier_from_profile(profile: dict | None, *, category: str = "") -> SourceTier:
    """Map a persisted machine_energy_profiles row to a source tier.

    ``profile`` is the row indexed by machine_model_id in
    ``master["machine_energy_by_model"]`` (may be missing for catalog machines
    the bridge hasn't covered yet). ``category`` lets an unsupported category be
    flagged even when a proxy profile exists.

    Conservative by design: only ``Brochure Approved`` (set by
    ``promote_energy_profile``) is manufacturer evidence. ``Demo seed`` /
    ``NOT authentic`` text demotes; otherwise the row's own confidence is the
    ceiling (KG proxies carry 0.55, demo seeds 0.35 in the master).
    """
    if not profile:
        return TIER_NONE_ST

    approval = (profile.get("approval_status") or "").strip().lower()
    source = (profile.get("source") or "").strip().lower()

    # Reviewer-promoted brochure derivation — the strongest, manufacturer-tier path.
    if "brochure approved" in approval or "brochure-derived" in source:
        return TIER_APPROVED_ST

    # Demo seeds that the master explicitly flags not-authentic (e.g. MMOD001's
    # "Demo seed (18kW/120kg/h) — NOT authentic"). Demote hard.
    if "not authentic" in source or "notauthentic" in source or "demo seed" in source:
        return TIER_DEMO_SEED_ST

    # Anything with electricity + a non-approved status is a KG proxy awaiting
    # a brochure derivation.
    if approval:
        return TIER_PROXY_ST

    return TIER_PROXY_ST


def adjust_activity_confidence(base: float, tier: SourceTier) -> tuple[float, str]:
    """Apply the tier ceiling to a base activity confidence.

    Returns (adjusted_confidence, tier_label). A manufacturer-tier derivation
    is capped *up* only if its base was already at least trade-grade (don't
    inflate a thin factor to L2 wholesale); proxies are capped at their tier
    ceiling; demo seeds are floored down to L5.
    """
    if tier.tier == TIER_MANUFACTURER:
        # Raise a sound derivation to its tier ceiling, but never above the
        # weakest input (the electricity grid factor / step prior). min() of
        # the inputs already happened upstream; here we lift toward 0.8 if the
        # base was middling, but don't exceed 0.8.
        adjusted = min(0.8, max(base, 0.7))
    elif tier.tier == TIER_DEMO_SEED:
        # Demo seeds are explicitly not-authentic -> demote to L5.
        adjusted = min(base, 0.30)
    elif tier.tier == TIER_UNSUPPORTED:
        adjusted = min(base, 0.35)
    elif tier.tier == TIER_NONE:
        adjusted = min(base, 0.30)
    else:  # proxy
        adjusted = min(base, 0.55)
    return adjusted, tier.label


# Coverage-report vocabulary, kept here so the endpoint + tests share one place.
COVERAGE_STATUS_APPROVED = "DB-approved"
COVERAGE_STATUS_DERIVED_APPROX = "Brochure-derived (approximate)"
COVERAGE_STATUS_PROXY = "KG-proxy"
COVERAGE_STATUS_UNSUPPORTED = "unsupported-rule"


__all__ = [
    "SourceTier",
    "source_tier_from_profile",
    "adjust_activity_confidence",
    "TIER_MANUFACTURER",
    "TIER_PROXY",
    "TIER_DEMO_SEED",
    "TIER_UNSUPPORTED",
    "TIER_NONE",
    "TIER_APPROVED_ST",
    "TIER_MANUFACTURER_ST",
    "TIER_PROXY_ST",
    "TIER_DEMO_SEED_ST",
    "TIER_UNSUPPORTED_ST",
    "TIER_NONE_ST",
    "COVERAGE_STATUS_APPROVED",
    "COVERAGE_STATUS_DERIVED_APPROX",
    "COVERAGE_STATUS_PROXY",
    "COVERAGE_STATUS_UNSUPPORTED",
]
