"""Declarative missing-information detection; this service never guesses."""
from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any, Callable


@dataclass(frozen=True)
class InformationGap:
    gap_id: str
    path: str
    reason: str
    severity: str
    requested_information: str
    status: str = "open"

    def to_dict(self) -> dict[str, str]:
        return asdict(self)


@dataclass(frozen=True)
class GapRule:
    gap_id: str
    predicate: Callable[[dict[str, Any]], bool]
    path: str
    reason: str
    severity: str
    requested_information: str


def _signals_missing_composition(sections: dict[str, Any]) -> bool:
    signals = sections.get("signals") or {}
    return not signals.get("bom_components") and not signals.get("blend")


def _signals_missing_origin(sections: dict[str, Any]) -> bool:
    signals = sections.get("signals") or {}
    return not signals.get("declared_origin") and not sections.get("origin_context")


def _proxy_machine_data(sections: dict[str, Any]) -> bool:
    resources = sections.get("resources") or {}
    rows = resources.get("machine_breakdown") or []
    return any(isinstance(row, dict) and row.get("source_tier") not in {None, "manufacturer"} for row in rows)


DEFAULT_GAP_RULES = (
    GapRule(
        "GAP-MATERIAL-COMPOSITION", _signals_missing_composition, "sections.signals", "No material composition was supplied.", "high", "BOM component material and quantity.",
    ),
    GapRule(
        "GAP-PRODUCTION-ORIGIN", _signals_missing_origin, "sections.origin_context", "No production origin is evidenced.", "medium", "Declared manufacturing country or facility.",
    ),
    GapRule(
        "GAP-MACHINE-PRIMARY-DATA", _proxy_machine_data, "sections.resources.machine_breakdown", "Machine energy uses a non-manufacturer proxy.", "medium", "Manufacturer brochure, model, and measured operating data.",
    ),
)


def detect_gaps(sections: dict[str, Any], *, rules: tuple[GapRule, ...] = DEFAULT_GAP_RULES) -> list[dict[str, str]]:
    """Return unresolved facts; callers must not substitute assumptions."""
    return [
        InformationGap(rule.gap_id, rule.path, rule.reason, rule.severity, rule.requested_information).to_dict()
        for rule in rules
        if rule.predicate(sections)
    ]


__all__ = ["DEFAULT_GAP_RULES", "GapRule", "InformationGap", "detect_gaps"]
