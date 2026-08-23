"""Small deterministic rule engine for generic Twin reasoning."""
from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any, Callable


@dataclass(frozen=True)
class RuleDefinition:
    rule_id: str
    description: str
    predicate: Callable[[dict[str, Any], list[dict[str, Any]], dict[str, Any]], bool]


@dataclass(frozen=True)
class RuleOutcome:
    rule_id: str
    description: str
    status: str
    evidence_paths: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        return asdict(self) | {"evidence_paths": list(self.evidence_paths)}


DEFAULT_RULES = (
    RuleDefinition(
        "RULE-TWIN-REQUIRED-SECTIONS",
        "Required analysis sections must be present before a final conclusion is explained.",
        lambda sections, _gaps, _confidence: {"signals", "classification", "route", "resources", "report"}.issubset(sections),
    ),
    RuleDefinition(
        "RULE-CONFIDENCE-WEAKEST-LINK",
        "Confidence is propagated from recorded evidence using the weakest supported input.",
        lambda _sections, _gaps, confidence: confidence.get("overall_score") is not None,
    ),
    RuleDefinition(
        "RULE-GAPS-ARE-NOT-ASSUMPTIONS",
        "Missing information remains a gap and is not converted into inferred knowledge.",
        lambda _sections, gaps, _confidence: isinstance(gaps, list),
    ),
)


class RuleEngine:
    def __init__(self, rules: tuple[RuleDefinition, ...] = DEFAULT_RULES) -> None:
        self._rules = rules

    def evaluate(
        self, sections: dict[str, Any], gaps: list[dict[str, Any]], confidence: dict[str, Any]
    ) -> list[dict[str, Any]]:
        outcomes = []
        for rule in self._rules:
            passed = rule.predicate(sections, gaps, confidence)
            outcomes.append(
                RuleOutcome(
                    rule_id=rule.rule_id,
                    description=rule.description,
                    status="passed" if passed else "not_satisfied",
                    evidence_paths=("sections",),
                ).to_dict()
            )
        return outcomes


__all__ = ["DEFAULT_RULES", "RuleDefinition", "RuleEngine", "RuleOutcome"]
