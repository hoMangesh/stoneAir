from app.core.knowledge import Evidence, KnowledgeEntity
from app.services.knowledge_repository import repository_for_domain
from app.services.knowledge_verification import verify_entity, verify_repository


def test_apparel_repository_verifies_without_mutating_existing_masters():
    report = verify_repository(repository_for_domain("apparel"))
    assert report["status"] == "pass"
    assert report["entity_count"] > 0
    assert report["valid_count"] == report["entity_count"]
    assert report["entity_counts"]["material"] > 0
    assert report["entity_counts"]["emission_factor"] > 0
    assert 0.0 <= report["average_structural_confidence"] <= 1.0


def test_verification_reports_missing_provenance_as_an_error():
    entity = KnowledgeEntity(
        entity_type="material", entity_id="M-1", domain_id="test", version="1",
        source="", evidence=(), confidence=0.5, approval_status="Approved",
    )
    record = verify_entity(entity)
    assert record["status"] == "invalid"
    assert {finding["code"] for finding in record["findings"]} >= {"missing_source", "missing_evidence"}


def test_structural_confidence_is_separate_from_source_confidence():
    entity = KnowledgeEntity(
        entity_type="material", entity_id="M-2", domain_id="test", version="1",
        source="primary", evidence=(Evidence("E-1", "source", "primary"),), confidence=0.4,
        approval_status="Approved", effective_date="2026-01-01",
    )
    record = verify_entity(entity)
    assert record["source_confidence"] == 0.4
    assert record["structural_confidence"] == 0.58
