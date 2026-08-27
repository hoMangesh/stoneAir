"""Independently mountable, domain-neutral enterprise operations API."""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from app.core.enterprise import public_record
from app.services.enterprise_operations import AccessDenied, EnterpriseOperations, ResourceNotFound


router = APIRouter(prefix="/api/operations", tags=["operations"])
operations = EnterpriseOperations()


class OrganizationRequest(BaseModel):
    name: str
    owner_id: str


class ScopedRequest(BaseModel):
    organization_id: str
    actor_id: str


class WorkspaceRequest(ScopedRequest):
    name: str


class ProjectRequest(WorkspaceRequest):
    workspace_id: str


class AnalysisRequest(ScopedRequest):
    workspace_id: str
    project_id: str
    twin_id: str


class QueueRequest(BaseModel):
    organization_id: str
    actor_id: str
    max_attempts: int = Field(default=3, ge=1, le=10)


class JobFailureRequest(BaseModel):
    worker_id: str
    error: str


class FeatureFlagRequest(BaseModel):
    organization_id: str
    actor_id: str
    name: str
    enabled: bool
    workspace_id: str | None = None


def _guard(callable_: Any) -> Any:
    try:
        return callable_()
    except (AccessDenied, ResourceNotFound) as exc:
        raise HTTPException(status_code=403 if isinstance(exc, AccessDenied) else 404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.post("/organizations")
def create_organization(request: OrganizationRequest) -> dict[str, Any]:
    return public_record(_guard(lambda: operations.create_organization(name=request.name, owner_id=request.owner_id)))


@router.post("/workspaces")
def create_workspace(request: WorkspaceRequest) -> dict[str, Any]:
    return public_record(_guard(lambda: operations.create_workspace(**request.model_dump())))


@router.post("/projects")
def create_project(request: ProjectRequest) -> dict[str, Any]:
    return public_record(_guard(lambda: operations.create_project(**request.model_dump())))


@router.post("/analyses")
def create_analysis(request: AnalysisRequest) -> dict[str, Any]:
    return public_record(_guard(lambda: operations.create_analysis(**request.model_dump())))


@router.post("/analyses/{analysis_id}/queue")
def queue_analysis(analysis_id: str, request: QueueRequest) -> dict[str, Any]:
    return public_record(_guard(lambda: operations.enqueue_analysis(analysis_id=analysis_id, **request.model_dump())))


@router.post("/jobs/claim")
def claim_job(worker_id: str) -> dict[str, Any]:
    job = _guard(lambda: operations.claim_next_job(worker_id=worker_id))
    return {"job": public_record(job) if job else None}


@router.post("/jobs/{job_id}/complete")
def complete_job(job_id: str, worker_id: str) -> dict[str, Any]:
    return public_record(_guard(lambda: operations.complete_job(job_id=job_id, worker_id=worker_id)))


@router.post("/jobs/{job_id}/fail")
def fail_job(job_id: str, request: JobFailureRequest) -> dict[str, Any]:
    return public_record(_guard(lambda: operations.fail_job(job_id=job_id, **request.dict())))


@router.put("/feature-flags")
def set_feature_flag(request: FeatureFlagRequest) -> dict[str, Any]:
    _guard(lambda: operations.set_feature_flag(**request.model_dump()))
    return {"status": "ok"}


@router.get("/audit")
def audit_log(organization_id: str, actor_id: str) -> dict[str, Any]:
    return {"entries": _guard(lambda: operations.audit_log(organization_id=organization_id, actor_id=actor_id))}


@router.get("/observability")
def observability(organization_id: str, actor_id: str) -> dict[str, Any]:
    return _guard(lambda: operations.operations_snapshot(organization_id=organization_id, actor_id=actor_id))


__all__ = ["operations", "router"]
