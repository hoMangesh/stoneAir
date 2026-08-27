"""Domain-neutral enterprise control-plane contracts.

These records are immutable metadata.  They reference a Twin by ID but never
contain, transform, or duplicate product/domain knowledge.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from typing import Any, Literal, Protocol
from uuid import uuid4


Role = Literal["owner", "admin", "analyst", "viewer"]
AnalysisStatus = Literal["draft", "queued", "running", "completed", "failed", "cancelled"]
JobStatus = Literal["queued", "running", "retry_wait", "succeeded", "failed", "cancelled"]


def now_utc() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def new_id(prefix: str) -> str:
    return f"{prefix}-{uuid4().hex[:16]}"


@dataclass(frozen=True)
class Organization:
    organization_id: str
    name: str
    created_at: str


@dataclass(frozen=True)
class Workspace:
    workspace_id: str
    organization_id: str
    name: str
    created_at: str


@dataclass(frozen=True)
class Membership:
    organization_id: str
    actor_id: str
    role: Role


@dataclass(frozen=True)
class Project:
    project_id: str
    organization_id: str
    workspace_id: str
    name: str
    status: Literal["active", "archived"]
    created_by: str
    created_at: str


@dataclass(frozen=True)
class Analysis:
    analysis_id: str
    organization_id: str
    workspace_id: str
    project_id: str
    twin_id: str
    status: AnalysisStatus
    created_by: str
    created_at: str
    updated_at: str


@dataclass(frozen=True)
class Job:
    job_id: str
    organization_id: str
    workspace_id: str
    analysis_id: str
    job_type: str
    status: JobStatus
    attempt: int
    max_attempts: int
    available_at: str
    created_at: str
    updated_at: str
    last_error: str | None = None


@dataclass(frozen=True)
class AuditEntry:
    audit_id: str
    organization_id: str
    actor_id: str
    action: str
    resource_type: str
    resource_id: str
    occurred_at: str
    request_id: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class PlatformEvent:
    event_id: str
    organization_id: str
    event_type: str
    resource_type: str
    resource_id: str
    occurred_at: str
    payload: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class Notification:
    notification_id: str
    organization_id: str
    actor_id: str
    event_id: str
    channel: Literal["in_app"]
    status: Literal["pending", "delivered"]
    created_at: str


class EnterpriseRepository(Protocol):
    """Storage port. Production adapters may provide transactional persistence."""

    def save(self, record: Any) -> None: ...

    def get(self, resource_type: str, resource_id: str) -> Any | None: ...

    def list(self, resource_type: str, organization_id: str) -> list[Any]: ...


def public_record(record: Any) -> dict[str, Any]:
    """Serialize immutable enterprise metadata without leaking implementation state."""
    return asdict(record)


__all__ = [
    "Analysis", "AnalysisStatus", "AuditEntry", "EnterpriseRepository", "Job", "JobStatus", "Membership",
    "Notification", "Organization", "PlatformEvent", "Project", "Role", "Workspace", "new_id", "now_utc", "public_record",
]
