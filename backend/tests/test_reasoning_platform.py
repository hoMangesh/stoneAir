from app.core.twin import ProductDigitalTwin
from app.services.reasoning_engine import ReasoningEngine


def _twin() -> ProductDigitalTwin:
    twin = ProductDigitalTwin.create(domain_id="generic", input_data={"source": "upload"})
    twin.enrich(
        section="signals",
        owner="service.signals",
        value={"bom_components": [], "blend": [], "declared_origin": None, "source": "bom", "confidence": {"score": 0.9}},
    )
    twin.enrich(section="classification", owner="service.classification", value={"label": "generic-product", "source": "rule", "confidence": {"score": 0.8}})
    twin.enrich(section="template", owner="service.template", value={"source": "catalog", "confidence": {"score": 0.7}})
    twin.enrich(section="route", owner="service.route", value={"source": "rule", "confidence": {"score": 0.75}})
    twin.enrich(section="origin_context", owner="service.origin", value=None)
    twin.enrich(
        section="resources",
        owner="service.resources",
        value={"machine_breakdown": [{"machine": "M-1", "source_tier": "proxy", "source": "reference", "confidence": {"score": 0.6}}]},
    )
    twin.enrich(section="report", owner="service.report", value={"source": "calculation", "confidence": {"score": 0.65}})
    twin.enrich(section="inference_trace", owner="service.trace", value=[{"inference_type": "route", "source": "rule", "evidence": ["ROUTE-1"], "confidence": {"score": 0.75}}])
    return twin


def test_reasoning_enriches_only_canonical_twin_and_records_gaps():
    twin = _twin()
    initial_version = twin.version

    result = ReasoningEngine().enrich(twin)

    assert twin.version == initial_version + 1
    assert twin.lifecycle_stage == "reasoned"
    assert twin.sections["reasoning"] == result
    assert result["confidence"]["overall_score"] == 0.6
    assert {gap["gap_id"] for gap in result["gaps"]} == {
        "GAP-MATERIAL-COMPOSITION",
        "GAP-PRODUCTION-ORIGIN",
        "GAP-MACHINE-PRIMARY-DATA",
    }
    assert result["interpretation"]["mode"] == "bounded_interpretation"
    assert result["evidence_graph"]["nodes"]


def test_reasoning_is_domain_agnostic_and_never_invents_confidence():
    twin = ProductDigitalTwin.create(domain_id="electronics", input_data={})
    result = ReasoningEngine().enrich(twin)

    assert result["confidence"]["overall_score"] is None
    assert result["confidence"]["section_scores"]["input"]["score"] is None
    assert result["interpretation"]["knowledge_policy"].startswith("Uses only recorded evidence")
