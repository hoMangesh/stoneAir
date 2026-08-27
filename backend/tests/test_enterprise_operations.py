import pytest

from app.services.enterprise_operations import AccessDenied, EnterpriseOperations, ResourceNotFound


def _context() -> tuple[EnterpriseOperations, str, str, str, str]:
    operations = EnterpriseOperations()
    organization = operations.create_organization(name="Acme", owner_id="owner")
    workspace = operations.create_workspace(organization_id=organization.organization_id, name="Sustainability", actor_id="owner")
    project = operations.create_project(organization_id=organization.organization_id, workspace_id=workspace.workspace_id, name="FY26", actor_id="owner")
    return operations, organization.organization_id, workspace.workspace_id, project.project_id, "owner"


def test_tenant_rbac_lifecycle_and_retryable_jobs_are_control_plane_only():
    operations, organization_id, workspace_id, project_id, owner = _context()
    operations.add_member(organization_id=organization_id, actor_id="analyst", role="analyst", performed_by=owner)
    analysis = operations.create_analysis(
        organization_id=organization_id, workspace_id=workspace_id, project_id=project_id, twin_id="TWIN-001", actor_id="analyst"
    )
    job = operations.enqueue_analysis(organization_id=organization_id, analysis_id=analysis.analysis_id, actor_id="analyst", max_attempts=2)
    claimed = operations.claim_next_job(worker_id="worker-a")

    assert claimed is not None
    assert claimed.job_id == job.job_id
    retry = operations.fail_job(job_id=job.job_id, worker_id="worker-a", error="transient")
    assert retry.status == "retry_wait"
    assert retry.attempt == 1
    retry = operations.claim_next_job(worker_id="worker-a", now="9999-01-01T00:00:00Z")
    assert retry is not None
    completed = operations.complete_job(job_id=job.job_id, worker_id="worker-a")

    assert completed.status == "succeeded"
    snapshot = operations.operations_snapshot(organization_id=organization_id, actor_id=owner)
    assert snapshot["jobs_by_status"]["succeeded"] == 1
    assert snapshot["audit_count"] >= 5
    assert snapshot["notification_count"] == 1


def test_rbac_and_tenant_boundaries_are_enforced():
    operations, organization_id, workspace_id, project_id, owner = _context()
    other = operations.create_organization(name="Other", owner_id="other-owner")

    with pytest.raises(AccessDenied):
        operations.create_project(organization_id=organization_id, workspace_id=workspace_id, name="blocked", actor_id="unknown")
    with pytest.raises(ResourceNotFound):
        operations.create_project(organization_id=other.organization_id, workspace_id=workspace_id, name="cross-tenant", actor_id="other-owner")
    with pytest.raises(AccessDenied):
        operations.audit_log(organization_id=organization_id, actor_id="unknown")


def test_feature_flags_are_tenant_scoped_with_workspace_override():
    operations, organization_id, workspace_id, _project_id, owner = _context()
    operations.set_feature_flag(organization_id=organization_id, name="async-analysis", enabled=True, actor_id=owner)
    operations.set_feature_flag(organization_id=organization_id, workspace_id=workspace_id, name="async-analysis", enabled=False, actor_id=owner)

    assert operations.feature_enabled(organization_id=organization_id, name="async-analysis") is True
    assert operations.feature_enabled(organization_id=organization_id, workspace_id=workspace_id, name="async-analysis") is False
