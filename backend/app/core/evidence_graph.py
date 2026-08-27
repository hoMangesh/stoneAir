"""Domain-agnostic evidence graph primitives for Twin reasoning."""
from __future__ import annotations

from dataclasses import asdict, dataclass
from hashlib import sha256
from typing import Any, Iterable


@dataclass(frozen=True)
class EvidenceNode:
    evidence_id: str
    subject_path: str
    claim: str
    source: str
    confidence_score: float | None
    evidence_refs: tuple[str, ...]
    approval_status: str | None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self) | {"evidence_refs": list(self.evidence_refs)}


@dataclass(frozen=True)
class EvidenceEdge:
    from_id: str
    to_id: str
    relation: str = "supports"

    def to_dict(self) -> dict[str, str]:
        return asdict(self)


def evidence_id(*, subject_path: str, source: str, claim: str) -> str:
    """Create a deterministic identifier; IDs never encode domain vocabulary."""
    fingerprint = sha256(f"{subject_path}|{source}|{claim}".encode()).hexdigest()[:16]
    return f"EV-{fingerprint}"


def confidence_score(value: Any) -> float | None:
    """Read a supported confidence representation without fabricating one."""
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return max(0.0, min(1.0, float(value)))
    if isinstance(value, dict):
        for key in ("score", "overall_score"):
            if isinstance(value.get(key), (int, float)):
                return max(0.0, min(1.0, float(value[key])))
    return None


def _as_refs(value: Any) -> tuple[str, ...]:
    if not isinstance(value, list):
        return ()
    refs: list[str] = []
    for item in value:
        if isinstance(item, str):
            refs.append(item)
        elif isinstance(item, dict):
            reference = item.get("id") or item.get("source") or item.get("reference")
            if reference:
                refs.append(str(reference))
    return tuple(refs)


def _walk(value: Any, path: str) -> Iterable[tuple[str, dict[str, Any]]]:
    if isinstance(value, dict):
        if any(key in value for key in ("confidence", "source", "evidence")):
            yield path, value
        for key, child in value.items():
            yield from _walk(child, f"{path}.{key}")
    elif isinstance(value, list):
        for index, child in enumerate(value):
            yield from _walk(child, f"{path}[{index}]")


def build_evidence_graph(sections: dict[str, Any]) -> dict[str, list[dict[str, Any]]]:
    """Project source-bearing Twin claims into an immutable graph view.

    Only values that already carry provenance, evidence, or confidence become
    graph nodes.  The graph therefore records absence rather than filling it.
    """
    nodes: list[EvidenceNode] = []
    for path, claim_value in _walk(sections, "sections"):
        confidence = confidence_score(claim_value.get("confidence"))
        source = str(claim_value.get("source") or "twin-derived")
        refs = _as_refs(claim_value.get("evidence"))
        claim = str(
            claim_value.get("inference_type")
            or claim_value.get("activity_id")
            or claim_value.get("process")
            or claim_value.get("label")
            or path
        )
        nodes.append(
            EvidenceNode(
                evidence_id=evidence_id(subject_path=path, source=source, claim=claim),
                subject_path=path,
                claim=claim,
                source=source,
                confidence_score=confidence,
                evidence_refs=refs,
                approval_status=(str(claim_value["approval_status"]) if claim_value.get("approval_status") else None),
            )
        )
    edges = [
        EvidenceEdge(from_id=node.evidence_id, to_id=reference)
        for node in nodes
        for reference in node.evidence_refs
    ]
    return {"nodes": [node.to_dict() for node in nodes], "edges": [edge.to_dict() for edge in edges]}


__all__ = ["EvidenceEdge", "EvidenceNode", "build_evidence_graph", "confidence_score"]
