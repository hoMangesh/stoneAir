from app.api.explainability import ExplainabilityRequest, explain_twin
from app.core.twin import ProductDigitalTwin


def test_explainability_api_returns_a_reasoned_twin_without_external_state():
    twin = ProductDigitalTwin.create(domain_id="generic", input_data={"source": "test"})

    response = explain_twin(ExplainabilityRequest(twin=twin.to_dict()))

    assert response["twin"]["twin_id"] == twin.twin_id
    assert response["twin"]["sections"]["reasoning"] == response["explainability"]
    assert response["explainability"]["interpretation"]["mode"] == "bounded_interpretation"
