"""Conservative, domain-agnostic confidence propagation for Twin sections."""
from __future__ import annotations

from typing import Any

from app.core.evidence_graph import confidence_score


def _scores(value: Any) -> list[float]:
    scores: list[float] = []
    if isinstance(value, dict):
        if "confidence" in value:
            score = confidence_score(value["confidence"])
            if score is not None:
                scores.append(score)
        for child in value.values():
            scores.extend(_scores(child))
    elif isinstance(value, list):
        for child in value:
            scores.extend(_scores(child))
    return scores


def propagate_confidence(sections: dict[str, Any]) -> dict[str, Any]:
    """Propagate confidence using a weakest-link model, never an estimate.

    A downstream conclusion is only as credible as its least-supported input.
    Sections without recorded confidence are reported as uncovered rather than
    receiving a default score.
    """
    section_scores: dict[str, dict[str, Any]] = {}
    covered: list[float] = []
    for section, value in sections.items():
        scores = _scores(value)
        if scores:
            propagated = min(scores)
            covered.append(propagated)
            section_scores[section] = {
                "score": round(propagated, 4),
                "input_count": len(scores),
                "method": "weakest_link",
            }
        else:
            section_scores[section] = {"score": None, "input_count": 0, "method": "uncovered"}
    return {
        "overall_score": round(min(covered), 4) if covered else None,
        "method": "weakest_link",
        "covered_section_count": len(covered),
        "section_scores": section_scores,
    }


__all__ = ["propagate_confidence"]
