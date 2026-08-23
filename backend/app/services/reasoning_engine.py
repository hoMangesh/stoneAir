"""Domain-agnostic reasoning orchestration over the canonical Product Twin."""
from __future__ import annotations

from copy import deepcopy
from typing import Any

from app.core.confidence import propagate_confidence
from app.core.evidence_graph import build_evidence_graph
from app.core.rules import RuleEngine
from app.core.twin import ProductDigitalTwin
from app.services.gap_detection import detect_gaps


def interpret_reasoning(reasoning: dict[str, Any]) -> dict[str, Any]:
    """Produce a bounded explanation exclusively from the reasoning result.

    This is the AI interpretation boundary.  It is intentionally provider-free:
    a future LLM adapter receives only this verified payload and must return an
    explanation constrained to its IDs, scores, rules, and gaps.
    """
    graph = reasoning["evidence_graph"]
    confidence = reasoning["confidence"]
    gaps = reasoning["gaps"]
    rules = reasoning["rules"]
    score = confidence.get("overall_score")
    score_text = "uncovered" if score is None else f"{score:.2f}"
    statements = [
        f"Evidence graph contains {len(graph['nodes'])} recorded claims and {len(graph['edges'])} support links.",
        f"End-to-end confidence is {score_text} using the {confidence['method']} method.",
        f"Deterministic rules evaluated: {len(rules)}; open information gaps: {len(gaps)}.",
    ]
    if gaps:
        statements.append("Open gaps: " + "; ".join(f"{gap['gap_id']} at {gap['path']}" for gap in gaps) + ".")
    return {
        "mode": "bounded_interpretation",
        "knowledge_policy": "Uses only recorded evidence, rule outcomes, gaps, and confidence; it does not add facts or estimates.",
        "statements": statements,
        "cited_evidence_ids": [node["evidence_id"] for node in graph["nodes"]],
        "cited_rule_ids": [rule["rule_id"] for rule in rules],
        "cited_gap_ids": [gap["gap_id"] for gap in gaps],
    }


class ReasoningEngine:
    """Enrich exactly one Twin; no domain pack or parallel mutable state exists."""

    def __init__(self, *, rule_engine: RuleEngine | None = None) -> None:
        self._rule_engine = rule_engine or RuleEngine()

    def evaluate(self, twin: ProductDigitalTwin) -> dict[str, Any]:
        """Build a serializable explanation using only existing Twin facts."""
        twin.validate()
        source_sections = {key: value for key, value in twin.sections.items() if key != "reasoning"}
        evidence_graph = build_evidence_graph(source_sections)
        confidence = propagate_confidence(source_sections)
        gaps = detect_gaps(source_sections)
        rules = self._rule_engine.evaluate(source_sections, gaps, confidence)
        reasoning = {
            "schema_version": "1.0",
            "owner": "core.reasoning",
            "evidence_graph": evidence_graph,
            "confidence": confidence,
            "gaps": gaps,
            "rules": rules,
        }
        reasoning["interpretation"] = interpret_reasoning(reasoning)
        return reasoning

    def enrich(self, twin: ProductDigitalTwin) -> dict[str, Any]:
        """Attach reasoning to the canonical Twin as its sole state mutation."""
        reasoning = self.evaluate(twin)
        twin.enrich(section="reasoning", value=reasoning, owner="core.reasoning")
        return deepcopy(reasoning)


def enrich_twin(twin: ProductDigitalTwin) -> dict[str, Any]:
    """Convenience entry point for dependency-injected application services."""
    return ReasoningEngine().enrich(twin)


__all__ = ["ReasoningEngine", "enrich_twin", "interpret_reasoning"]
