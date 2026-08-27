from app.api import operations as api
from app.api.operations import AnalysisRequest, OrganizationRequest, ProjectRequest, QueueRequest, WorkspaceRequest


def test_operations_api_exposes_tenant_scoped_analysis_lifecycle(monkeypatch):
    # Replace the module singleton to keep this API-contract test isolated.
    from app.services.enterprise_operations import EnterpriseOperations

    monkeypatch.setattr(api, "operations", EnterpriseOperations())
    organization = api.create_organization(OrganizationRequest(name="Acme", owner_id="owner"))
    workspace = api.create_workspace(WorkspaceRequest(organization_id=organization["organization_id"], name="Ops", actor_id="owner"))
    project = api.create_project(ProjectRequest(organization_id=organization["organization_id"], workspace_id=workspace["workspace_id"], name="P", actor_id="owner"))
    analysis = api.create_analysis(AnalysisRequest(organization_id=organization["organization_id"], workspace_id=workspace["workspace_id"], project_id=project["project_id"], twin_id="TWIN-1", actor_id="owner"))
    job = api.queue_analysis(analysis["analysis_id"], QueueRequest(organization_id=organization["organization_id"], actor_id="owner"))

    claimed = api.claim_job(worker_id="worker")["job"]
    completed = api.complete_job(job["job_id"], worker_id="worker")
    metrics = api.observability(organization_id=organization["organization_id"], actor_id="owner")

    assert claimed["status"] == "running"
    assert completed["status"] == "succeeded"
    assert metrics["jobs_by_status"]["succeeded"] == 1
