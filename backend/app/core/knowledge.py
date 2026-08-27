"""Domain-neutral knowledge entity and repository contracts.

Knowledge masters remain domain-owned source data. This module defines the
stable, normalized representation consumed by governance, verification, and
future knowledge services; it contains no domain vocabulary or CSV assumptions.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol, runtime_checkable


@dataclass(frozen=True)
class Evidence:
    """A traceable assertion source attached to a canonical knowledge entity."""

    evidence_id: str
    kind: str
    reference: str
    excerpt: str = ""


@dataclass(frozen=True)
class KnowledgeEntity:
    """Canonical, domain-neutral master-data envelope.

    Entity-specific fields remain in ``attributes`` so materials, processes,
    machines, suppliers, geography, energy, and emission factors share the
    same governance surface without forcing a lossy common schema.
    """

    entity_type: str
    entity_id: str
    domain_id: str
    version: str
    source: str
    evidence: tuple[Evidence, ...]
    confidence: float
    approval_status: str
    effective_date: str = ""
    expiry_date: str = ""
    attributes: dict[str, Any] = field(default_factory=dict)


@runtime_checkable
class KnowledgeRepository(Protocol):
    """Read-only repository contract for canonical knowledge entities."""

    def get(self, *, entity_type: str, entity_id: str) -> KnowledgeEntity | None: ...
    def list(self, *, entity_type: str | None = None) -> list[KnowledgeEntity]: ...
    def provenance(self, *, entity_type: str, entity_id: str) -> tuple[Evidence, ...]: ...


CANONICAL_ENTITY_TYPES = frozenset({
    "material",
    "process",
    "machine",
    "supplier",
    "geography",
    "energy_profile",
    "emission_factor",
})


__all__ = ["Evidence", "KnowledgeEntity", "KnowledgeRepository", "CANONICAL_ENTITY_TYPES"]
