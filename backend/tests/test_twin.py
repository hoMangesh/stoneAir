import pytest

from app.core.twin import ProductDigitalTwin, TwinValidationError


def _complete_twin() -> ProductDigitalTwin:
    twin = ProductDigitalTwin.create(domain_id="apparel", input_data={"description": "tee"})
    for section in ("signals", "classification", "template", "route", "resources", "report", "inference_trace"):
        twin.enrich(section=section, value={"section": section}, owner=f"test.{section}")
    return twin


def test_twin_records_versioned_service_enrichments():
    twin = _complete_twin()
    twin.validate(final=True)
    payload = twin.to_dict()
    assert payload["schema_version"] == "1.0"
    assert payload["domain_id"] == "apparel"
    assert payload["version"] == 9
    assert payload["history"][-1]["owner"] == "test.inference_trace"


def test_twin_rejects_unknown_or_regressive_enrichment():
    twin = ProductDigitalTwin.create(domain_id="apparel", input_data={})
    with pytest.raises(TwinValidationError, match="unknown twin section"):
        twin.enrich(section="unknown", value={}, owner="test")
    twin.enrich(section="report", value={}, owner="test.report")
    with pytest.raises(TwinValidationError, match="cannot enrich"):
        twin.enrich(section="signals", value={}, owner="test.signals")


def test_final_twin_requires_all_canonical_analysis_sections():
    twin = ProductDigitalTwin.create(domain_id="apparel", input_data={})
    with pytest.raises(TwinValidationError, match="final twin missing"):
        twin.validate(final=True)
