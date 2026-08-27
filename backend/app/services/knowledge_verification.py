"""Generic, offline verification of canonical knowledge repository records."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from app.core.knowledge import KnowledgeEntity, KnowledgeRepository


@dataclass(frozen=True)
class VerificationFinding:
    code: str
    severity: str
    message: str


def _structural_confidence(entity: KnowledgeEntity) -> float:
    """Score governance completeness without modifying the source confidence.

    The raw master confidence remains the domain owner's assertion. This score
    answers a separate question: how complete is the record's audit/provenance
    envelope? Both appear in the verification result.
    """
    checks = (
        bool(entity.version),
        bool(entity.source),
        bool(entity.evidence),
        bool(entity.approval_status),
        bool(entity.effective_date),
    )
    completeness = sum(checks) / len(checks)
    return round((entity.confidence * 0.7) + (completeness * 0.3), 2)


def verify_entity(entity: KnowledgeEntity) -> dict[str, Any]:
    """Validate one entity's canonical governance and provenance envelope."""
    findings: list[VerificationFinding] = []
    if not entity.entity_id:
        findings.append(VerificationFinding("missing_id", "error", "entity_id is required"))
    if not entity.entity_type:
        findings.append(VerificationFinding("missing_type", "error", "entity_type is required"))
    if not entity.domain_id:
        findings.append(VerificationFinding("missing_domain", "error", "domain_id is required"))
    if not entity.version:
        findings.append(VerificationFinding("missing_version", "error", "version is required"))
    if not entity.source:
        findings.append(VerificationFinding("missing_source", "error", "source is required"))
    if not entity.evidence:
        findings.append(VerificationFinding("missing_evidence", "error", "at least one provenance evidence record is required"))
    if not entity.approval_status:
        findings.append(VerificationFinding("missing_approval", "warning", "approval_status is missing"))
    if not entity.effective_date:
        findings.append(VerificationFinding("missing_effective_date", "warning", "effective_date is missing"))
    if not 0.0 <= entity.confidence <= 1.0:
        findings.append(VerificationFinding("invalid_confidence", "error", "confidence must be within 0..1"))

    errors = [finding for finding in findings if finding.severity == "error"]
    return {
        "entity_type": entity.entity_type,
        "entity_id": entity.entity_id,
        "domain_id": entity.domain_id,
        "status": "invalid" if errors else "structurally_valid",
        "source_confidence": entity.confidence,
        "structural_confidence": _structural_confidence(entity),
        "provenance": [
            {"evidence_id": evidence.evidence_id, "kind": evidence.kind, "reference": evidence.reference, "excerpt": evidence.excerpt}
            for evidence in entity.evidence
        ],
        "findings": [finding.__dict__ for finding in findings],
    }


def verify_repository(repository: KnowledgeRepository) -> dict[str, Any]:
    """Verify every entity in a repository without changing source masters."""
    records = [verify_entity(entity) for entity in repository.list()]
    errors = sum(1 for record in records if record["status"] == "invalid")
    warnings = sum(
        1
        for record in records
        for finding in record["findings"]
        if finding["severity"] == "warning"
    )
    by_type: dict[str, int] = {}
    for record in records:
        by_type[record["entity_type"]] = by_type.get(record["entity_type"], 0) + 1
    return {
        "status": "pass" if not errors else "fail",
        "entity_count": len(records),
        "valid_count": len(records) - errors,
        "error_count": errors,
        "warning_count": warnings,
        "average_structural_confidence": round(
            sum(float(record["structural_confidence"]) for record in records) / len(records), 2
        ) if records else 0.0,
        "entity_counts": dict(sorted(by_type.items())),
        "records": records,
    }


__all__ = ["VerificationFinding", "verify_entity", "verify_repository"]
