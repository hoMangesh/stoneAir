"""Read-only adapter from domain master records to canonical knowledge entities."""
from __future__ import annotations

from typing import Any

from app.core.knowledge import Evidence, KnowledgeEntity
from app.services.knowledge_loader import load_master_data


_ENTITY_SPECS = {
    "material": ("materials", "material_id"),
    "process": ("processes", "process_id"),
    "machine": ("machine_models", "machine_model_id"),
    "supplier": ("suppliers", "supplier_id"),
    "geography": ("countries", "country_id"),
    "energy_profile": ("machine_energy_profiles", "machine_model_id"),
    "emission_factor": ("emission_factors", "factor_id"),
}


def _score(value: str | float | None) -> float:
    try:
        return max(0.0, min(float(value or 0.0), 1.0))
    except (TypeError, ValueError):
        return 0.0


def _entity_from_row(*, entity_type: str, row: dict[str, str], id_field: str, domain_id: str) -> KnowledgeEntity:
    entity_id = row.get(id_field, "")
    source = row.get("source", "")
    evidence = () if not source else (
        Evidence(
            evidence_id=f"{entity_type}:{entity_id}:source",
            kind="master_record_source",
            reference=source,
            excerpt=f"{entity_type} master record {entity_id}",
        ),
    )
    governance_fields = {"version", "source", "confidence", "approval_status", "effective_date", "expiry_date", id_field}
    return KnowledgeEntity(
        entity_type=entity_type,
        entity_id=entity_id,
        domain_id=domain_id,
        version=row.get("version", ""),
        source=source,
        evidence=evidence,
        confidence=_score(row.get("confidence")),
        approval_status=row.get("approval_status", ""),
        effective_date=row.get("effective_date", ""),
        expiry_date=row.get("expiry_date", ""),
        attributes={key: value for key, value in row.items() if key not in governance_fields},
    )


class MasterDataKnowledgeRepository:
    """Canonical, read-only view over a selected domain's existing masters.

    This is an adapter, not a replacement loader: calculation services continue
    to consume their current master-data indexes unchanged during migration.
    """

    def __init__(self, *, domain_id: str, master_data: dict[str, Any] | None = None):
        self.domain_id = domain_id
        self._master_data = master_data
        self._entities: list[KnowledgeEntity] | None = None

    def _all(self) -> list[KnowledgeEntity]:
        if self._entities is None:
            master = self._master_data or load_master_data()
            datasets = master["datasets"]
            entities: list[KnowledgeEntity] = []
            for entity_type, (dataset_name, id_field) in _ENTITY_SPECS.items():
                for row in datasets.get(dataset_name, []):
                    if row.get(id_field):
                        entities.append(_entity_from_row(
                            entity_type=entity_type,
                            row=row,
                            id_field=id_field,
                            domain_id=self.domain_id,
                        ))
            self._entities = entities
        return self._entities

    def get(self, *, entity_type: str, entity_id: str) -> KnowledgeEntity | None:
        return next((entity for entity in self._all() if entity.entity_type == entity_type and entity.entity_id == entity_id), None)

    def list(self, *, entity_type: str | None = None) -> list[KnowledgeEntity]:
        return [entity for entity in self._all() if entity_type is None or entity.entity_type == entity_type]

    def provenance(self, *, entity_type: str, entity_id: str) -> tuple[Evidence, ...]:
        entity = self.get(entity_type=entity_type, entity_id=entity_id)
        return entity.evidence if entity else ()


def repository_for_domain(domain_id: str | None = None) -> MasterDataKnowledgeRepository:
    """Create the generic repository view for a registered domain pack."""
    from app.core.domain_registry import resolve
    from domain_packs.bootstrap import bootstrap

    bootstrap()
    pack = resolve(domain_id)
    return MasterDataKnowledgeRepository(domain_id=pack.domain_id, master_data=load_master_data(pack))


__all__ = ["MasterDataKnowledgeRepository", "repository_for_domain"]
