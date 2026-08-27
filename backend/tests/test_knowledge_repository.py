from app.core.knowledge import CANONICAL_ENTITY_TYPES, KnowledgeRepository
from app.services.knowledge_repository import repository_for_domain


def test_apparel_masters_are_exposed_as_canonical_knowledge_entities():
    repository = repository_for_domain("apparel")
    assert isinstance(repository, KnowledgeRepository)
    material = repository.get(entity_type="material", entity_id="MAT001")
    assert material is not None
    assert material.domain_id == "apparel"
    assert material.version == "1.0"
    assert material.source == "Manufacturing_Knowledge_Graph_V1"
    assert material.evidence[0].kind == "master_record_source"
    assert material.confidence == 0.85


def test_repository_covers_all_required_canonical_entity_types():
    repository = repository_for_domain("apparel")
    represented = {entity.entity_type for entity in repository.list()}
    assert CANONICAL_ENTITY_TYPES <= represented
    assert repository.provenance(entity_type="emission_factor", entity_id="EF-ELEC-IND-2026")
