"""Canonical Product Digital Twin lifecycle.

The twin is the single in-memory aggregate for one analysis run. Services do
not construct a competing product state; each service enriches a named section
and records its ownership in the immutable lifecycle history. Persistence may
later store this contract, but Workstream 2 deliberately keeps storage additive
and preserves the existing report/inference persistence schema.
"""
from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any
from uuid import uuid4


TWIN_SCHEMA_VERSION = "1.0"

_SECTION_STAGES = {
    "input": "intake",
    "signals": "interpreted",
    "classification": "classified",
    "template": "templated",
    "composite_route": "routed",
    "route": "routed",
    "origin_context": "routed",
    "resources": "evaluated",
    "report": "reported",
    "inference_trace": "traced",
    # Optional, additive Workstream 4 enrichment. Existing pipelines remain
    # valid when no reasoning service has been configured.
    "reasoning": "reasoned",
    "workflow": "enriched",
    "brochure_enrichment": "enriched",
    "persistence": "persisted",
}
_STAGE_ORDER = {stage: index for index, stage in enumerate(dict.fromkeys(_SECTION_STAGES.values()))}
_REQUIRED_FINAL_SECTIONS = {"signals", "classification", "template", "route", "resources", "report", "inference_trace"}


class TwinValidationError(ValueError):
    """Raised when an enrichment violates the twin contract or lifecycle."""


@dataclass
class ProductDigitalTwin:
    """A versioned, canonical product-analysis aggregate for one run."""

    twin_id: str
    domain_id: str
    created_at: str
    schema_version: str = TWIN_SCHEMA_VERSION
    version: int = 1
    lifecycle_stage: str = "created"
    sections: dict[str, Any] = field(default_factory=dict)
    history: list[dict[str, Any]] = field(default_factory=list)

    @classmethod
    def create(cls, *, domain_id: str, input_data: dict[str, Any]) -> "ProductDigitalTwin":
        if not domain_id or not domain_id.strip():
            raise TwinValidationError("domain_id is required")
        twin = cls(
            twin_id=f"TWIN-{uuid4().hex[:16]}",
            domain_id=domain_id.strip().lower(),
            created_at=datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z"),
        )
        twin.enrich(section="input", value=input_data, owner="api.intake")
        return twin

    @classmethod
    def from_dict(cls, value: dict[str, Any]) -> "ProductDigitalTwin":
        """Rehydrate a serialized twin for stateless API consumers.

        The method deliberately accepts only the canonical public shape.  It
        does not restore or create any parallel product state.
        """
        required = {"twin_id", "domain_id", "created_at", "sections", "history"}
        missing = required.difference(value)
        if missing:
            raise TwinValidationError(f"serialized twin missing fields: {sorted(missing)}")
        twin = cls(
            twin_id=str(value["twin_id"]),
            domain_id=str(value["domain_id"]),
            created_at=str(value["created_at"]),
            schema_version=str(value.get("schema_version", TWIN_SCHEMA_VERSION)),
            version=int(value.get("version", 1)),
            lifecycle_stage=str(value.get("lifecycle_stage", "created")),
            sections=deepcopy(value["sections"]),
            history=deepcopy(value["history"]),
        )
        twin.validate()
        return twin

    def enrich(self, *, section: str, value: Any, owner: str) -> None:
        """Apply a service-owned enrichment and advance the lifecycle safely."""
        if section not in _SECTION_STAGES:
            raise TwinValidationError(f"unknown twin section: {section}")
        if not owner or not owner.strip():
            raise TwinValidationError("enrichment owner is required")
        stage = _SECTION_STAGES[section]
        current_rank = _STAGE_ORDER.get(self.lifecycle_stage, -1)
        incoming_rank = _STAGE_ORDER[stage]
        if incoming_rank < current_rank:
            raise TwinValidationError(
                f"cannot enrich {section!r} at stage {stage!r} after {self.lifecycle_stage!r}"
            )
        self.sections[section] = deepcopy(value)
        self.version += 1
        self.lifecycle_stage = stage
        self.history.append(
            {
                "version": self.version,
                "section": section,
                "owner": owner,
                "stage": stage,
                "timestamp": datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z"),
            }
        )

    def validate(self, *, final: bool = False) -> None:
        """Validate schema/version invariants; final mode checks analysis completeness."""
        if self.schema_version != TWIN_SCHEMA_VERSION:
            raise TwinValidationError(f"unsupported twin schema version: {self.schema_version}")
        if self.version != len(self.history) + 1:
            raise TwinValidationError("twin version does not match enrichment history")
        if final:
            missing = _REQUIRED_FINAL_SECTIONS.difference(self.sections)
            if missing:
                raise TwinValidationError(f"final twin missing sections: {sorted(missing)}")

    def to_dict(self) -> dict[str, Any]:
        """Return the public, serializable twin representation."""
        self.validate()
        return {
            "twin_id": self.twin_id,
            "schema_version": self.schema_version,
            "domain_id": self.domain_id,
            "version": self.version,
            "lifecycle_stage": self.lifecycle_stage,
            "created_at": self.created_at,
            "sections": deepcopy(self.sections),
            "history": deepcopy(self.history),
        }


__all__ = ["ProductDigitalTwin", "TwinValidationError", "TWIN_SCHEMA_VERSION"]
