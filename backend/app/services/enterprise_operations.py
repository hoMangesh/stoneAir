"""Enterprise control plane: tenancy, RBAC, lifecycle, jobs, and operations.

The default adapter is deliberately in-memory for the prototype.  Every stored
record is immutable and tenant-scoped; a durable adapter can satisfy the same
``EnterpriseRepository`` port later without touching domain services.
"""
from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime, timedelta
from threading import RLock
from typing import Any, Iterable

from app.core.enterprise import (
    Analysis, AuditEntry, Job, Membership, Notification, Organization, PlatformEvent, Project, Workspace,
    new_id, now_utc, public_record,
)


ROLE_PERMISSIONS = {
    "owner": frozenset({"organization:manage", "workspace:manage", "project:write", "analysis:run", "analysis:read", "audit:read", "operations:read", "feature:manage"}),
    "admin": frozenset({"workspace:manage", "project:write", "analysis:run", "analysis:read", "audit:read", "operations:read", "feature:manage"}),
    "analyst": frozenset({"project:write", "analysis:run", "analysis:read"}),
    "viewer": frozenset({"analysis:read"}),
}


class AccessDenied(PermissionError):
    pass


class ResourceNotFound(LookupError):
    pass


class InMemoryEnterpriseRepository:
    """Thread-safe replace-on-write adapter; records cannot be mutated in place."""

    def __init__(self) -> None:
        self._rows: dict[str, dict[str, Any]] = {}
        self._lock = RLock()

    def save(self, record: Any) -> None:
        resource_type, identifier = _resource_key(record)
        with self._lock:
            self._rows.setdefault(resource_type, {})[identifier] = record

    def get(self, resource_type: str, resource_id: str) -> Any | None:
        with self._lock:
            return self._rows.get(resource_type, {}).get(resource_id)

    def list(self, resource_type: str, organization_id: str) -> list[Any]:
        with self._lock:
            return [record for record in self._rows.get(resource_type, {}).values() if getattr(record, "organization_id", None) == organization_id]


def _resource_key(record: Any) -> tuple[str, str]:
    # Test the resource's own identifier before its tenant foreign key.
    for name, resource_type in (
        ("notification_id", "notification"), ("event_id", "event"), ("audit_id", "audit"),
        ("job_id", "job"), ("analysis_id", "analysis"), ("project_id", "project"),
        ("workspace_id", "workspace"), ("organization_id", "organization"),
    ):
        if hasattr(record, name):
            return resource_type, getattr(record, name)
    raise TypeError(f"unsupported enterprise record: {type(record)!r}")


class EnterpriseOperations:
    """Domain-free application service and a single operational policy point."""

    def __init__(self, repository: InMemoryEnterpriseRepository | None = None) -> None:
        self._repository = repository or InMemoryEnterpriseRepository()
        self._memberships: dict[tuple[str, str], Membership] = {}
        self._flags: dict[tuple[str, str | None, str], bool] = {}
        self._lock = RLock()

    def create_organization(self, *, name: str, owner_id: str, request_id: str | None = None) -> Organization:
        organization = Organization(new_id("ORG"), name.strip(), now_utc())
        if not organization.name or not owner_id:
            raise ValueError("organization name and owner_id are required")
        self._repository.save(organization)
        self._memberships[(organization.organization_id, owner_id)] = Membership(organization.organization_id, owner_id, "owner")
        self._audit(organization.organization_id, owner_id, "organization.create", "organization", organization.organization_id, request_id)
        return organization

    def add_member(self, *, organization_id: str, actor_id: str, role: str, performed_by: str) -> Membership:
        self.require(organization_id, performed_by, "organization:manage")
        if role not in ROLE_PERMISSIONS:
            raise ValueError(f"unsupported role: {role}")
        membership = Membership(organization_id, actor_id, role)  # type: ignore[arg-type]
        self._memberships[(organization_id, actor_id)] = membership
        self._audit(organization_id, performed_by, "membership.upsert", "membership", actor_id)
        return membership

    def require(self, organization_id: str, actor_id: str, permission: str) -> None:
        membership = self._memberships.get((organization_id, actor_id))
        if membership is None or permission not in ROLE_PERMISSIONS[membership.role]:
            raise AccessDenied(f"actor lacks {permission} in organization")

    def create_workspace(self, *, organization_id: str, name: str, actor_id: str) -> Workspace:
        self.require(organization_id, actor_id, "workspace:manage")
        workspace = Workspace(new_id("WSP"), organization_id, name.strip(), now_utc())
        if not workspace.name:
            raise ValueError("workspace name is required")
        self._repository.save(workspace)
        self._audit(organization_id, actor_id, "workspace.create", "workspace", workspace.workspace_id)
        return workspace

    def create_project(self, *, organization_id: str, workspace_id: str, name: str, actor_id: str) -> Project:
        self.require(organization_id, actor_id, "project:write")
        self._workspace(organization_id, workspace_id)
        project = Project(new_id("PRJ"), organization_id, workspace_id, name.strip(), "active", actor_id, now_utc())
        if not project.name:
            raise ValueError("project name is required")
        self._repository.save(project)
        self._audit(organization_id, actor_id, "project.create", "project", project.project_id)
        return project

    def create_analysis(self, *, organization_id: str, workspace_id: str, project_id: str, twin_id: str, actor_id: str) -> Analysis:
        self.require(organization_id, actor_id, "analysis:run")
        self._project(organization_id, workspace_id, project_id)
        if not twin_id:
            raise ValueError("twin_id is required; the Twin remains the sole mutable product aggregate")
        analysis = Analysis(new_id("ANL"), organization_id, workspace_id, project_id, twin_id, "draft", actor_id, now_utc(), now_utc())
        self._repository.save(analysis)
        self._audit(organization_id, actor_id, "analysis.create", "analysis", analysis.analysis_id, metadata={"twin_id": twin_id})
        return analysis

    def enqueue_analysis(self, *, organization_id: str, analysis_id: str, actor_id: str, max_attempts: int = 3) -> Job:
        self.require(organization_id, actor_id, "analysis:run")
        analysis = self._analysis(organization_id, analysis_id)
        if analysis.status not in {"draft", "failed"}:
            raise ValueError(f"analysis cannot be queued from {analysis.status}")
        job = Job(new_id("JOB"), organization_id, analysis.workspace_id, analysis_id, "analysis.run", "queued", 0, max_attempts, now_utc(), now_utc(), now_utc())
        self._repository.save(job)
        self._save_analysis(replace(analysis, status="queued", updated_at=now_utc()))
        self._emit(organization_id, "analysis.queued", "analysis", analysis_id, {"job_id": job.job_id})
        self._audit(organization_id, actor_id, "analysis.queue", "analysis", analysis_id, metadata={"job_id": job.job_id})
        return job

    def claim_next_job(self, *, worker_id: str, now: str | None = None) -> Job | None:
        current = now or now_utc()
        candidates = [job for job in self._all("job") if job.status in {"queued", "retry_wait"} and job.available_at <= current]
        if not candidates:
            return None
        job = sorted(candidates, key=lambda row: (row.available_at, row.created_at))[0]
        running = replace(job, status="running", attempt=job.attempt + 1, updated_at=current)
        self._repository.save(running)
        analysis = self._analysis(running.organization_id, running.analysis_id)
        self._save_analysis(replace(analysis, status="running", updated_at=current))
        self._emit(running.organization_id, "job.started", "job", running.job_id, {"worker_id": worker_id, "analysis_id": running.analysis_id})
        return running

    def complete_job(self, *, job_id: str, worker_id: str) -> Job:
        job = self._job(job_id)
        if job.status != "running":
            raise ValueError("only running jobs can complete")
        completed = replace(job, status="succeeded", updated_at=now_utc())
        self._repository.save(completed)
        analysis = self._analysis(job.organization_id, job.analysis_id)
        self._save_analysis(replace(analysis, status="completed", updated_at=now_utc()))
        event = self._emit(job.organization_id, "analysis.completed", "analysis", job.analysis_id, {"job_id": job_id, "worker_id": worker_id})
        self._notify(job.organization_id, event, actor_id=worker_id)
        return completed

    def fail_job(self, *, job_id: str, worker_id: str, error: str) -> Job:
        job = self._job(job_id)
        if job.status != "running":
            raise ValueError("only running jobs can fail")
        terminal = job.attempt >= job.max_attempts
        status = "failed" if terminal else "retry_wait"
        delay = timedelta(seconds=2 ** max(0, job.attempt - 1))
        available_at = (datetime.now(UTC) + delay).replace(microsecond=0).isoformat().replace("+00:00", "Z")
        failed = replace(job, status=status, available_at=available_at, updated_at=now_utc(), last_error=error[:500])
        self._repository.save(failed)
        if terminal:
            analysis = self._analysis(job.organization_id, job.analysis_id)
            self._save_analysis(replace(analysis, status="failed", updated_at=now_utc()))
            event = self._emit(job.organization_id, "analysis.failed", "analysis", job.analysis_id, {"job_id": job_id})
            self._notify(job.organization_id, event, actor_id=worker_id)
        self._audit(job.organization_id, worker_id, "job.fail", "job", job_id, metadata={"terminal": terminal})
        return failed

    def set_feature_flag(self, *, organization_id: str, name: str, enabled: bool, actor_id: str, workspace_id: str | None = None) -> None:
        self.require(organization_id, actor_id, "feature:manage")
        if workspace_id is not None:
            self._workspace(organization_id, workspace_id)
        self._flags[(organization_id, workspace_id, name)] = enabled
        self._audit(organization_id, actor_id, "feature.set", "feature", name, metadata={"enabled": enabled, "workspace_id": workspace_id})

    def feature_enabled(self, *, organization_id: str, name: str, workspace_id: str | None = None, default: bool = False) -> bool:
        return self._flags.get((organization_id, workspace_id, name), self._flags.get((organization_id, None, name), default))

    def operations_snapshot(self, *, organization_id: str, actor_id: str) -> dict[str, Any]:
        self.require(organization_id, actor_id, "operations:read")
        jobs = self._repository.list("job", organization_id)
        return {
            "organization_id": organization_id,
            "jobs_by_status": {status: sum(job.status == status for job in jobs) for status in ("queued", "running", "retry_wait", "succeeded", "failed", "cancelled")},
            "event_count": len(self._repository.list("event", organization_id)),
            "audit_count": len(self._repository.list("audit", organization_id)),
            "notification_count": len(self._repository.list("notification", organization_id)),
        }

    def audit_log(self, *, organization_id: str, actor_id: str) -> list[dict[str, Any]]:
        self.require(organization_id, actor_id, "audit:read")
        return [public_record(row) for row in self._repository.list("audit", organization_id)]

    def _workspace(self, organization_id: str, workspace_id: str) -> Workspace:
        workspace = self._repository.get("workspace", workspace_id)
        if workspace is None or workspace.organization_id != organization_id:
            raise ResourceNotFound("workspace not found in organization")
        return workspace

    def _project(self, organization_id: str, workspace_id: str, project_id: str) -> Project:
        project = self._repository.get("project", project_id)
        if project is None or project.organization_id != organization_id or project.workspace_id != workspace_id:
            raise ResourceNotFound("project not found in workspace")
        return project

    def _analysis(self, organization_id: str, analysis_id: str) -> Analysis:
        analysis = self._repository.get("analysis", analysis_id)
        if analysis is None or analysis.organization_id != organization_id:
            raise ResourceNotFound("analysis not found in organization")
        return analysis

    def _job(self, job_id: str) -> Job:
        job = self._repository.get("job", job_id)
        if job is None:
            raise ResourceNotFound("job not found")
        return job

    def _save_analysis(self, analysis: Analysis) -> None:
        self._repository.save(analysis)

    def _all(self, resource_type: str) -> Iterable[Any]:
        return [record for bucket in self._repository._rows.get(resource_type, {}).values() for record in [bucket]]

    def _audit(self, organization_id: str, actor_id: str, action: str, resource_type: str, resource_id: str, request_id: str | None = None, metadata: dict[str, Any] | None = None) -> None:
        self._repository.save(AuditEntry(new_id("AUD"), organization_id, actor_id, action, resource_type, resource_id, now_utc(), request_id, metadata or {}))

    def _emit(self, organization_id: str, event_type: str, resource_type: str, resource_id: str, payload: dict[str, Any]) -> PlatformEvent:
        event = PlatformEvent(new_id("EVT"), organization_id, event_type, resource_type, resource_id, now_utc(), payload)
        self._repository.save(event)
        return event

    def _notify(self, organization_id: str, event: PlatformEvent, *, actor_id: str) -> Notification:
        notification = Notification(new_id("NTF"), organization_id, actor_id, event.event_id, "in_app", "pending", now_utc())
        self._repository.save(notification)
        return notification


__all__ = ["AccessDenied", "EnterpriseOperations", "InMemoryEnterpriseRepository", "ROLE_PERMISSIONS", "ResourceNotFound"]
