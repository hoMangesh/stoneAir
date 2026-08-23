from app.core.domain_registry import known, resolve
from app.main import health


def test_dummy_pack_is_activated_at_backend_boot():
    assert "dummy" in known()
    pack = resolve("dummy")
    assert pack.product_intelligence.classify(signals=None)["taxonomy"]["taxonomy_id"] == "DUMMY-001"
    assert pack.route_resolver.resolve(taxonomy_id="DUMMY-001", signals=None, default_route_id=None)["route_id"] == "DUMMY-ROUTE"
    assert pack.report_builder.build(classification={}, template_match={}, route={}, resources={"totals": {}})["domain"] == "dummy"
    assert pack.carbon_model.evaluate(route_steps=[], weight_g=1)["totals"]["carbon_kgco2e"] == 0.0


def test_backend_health_boots_with_dummy_pack_active():
    assert health() == {"status": "ok"}
    assert "dummy" in known()
