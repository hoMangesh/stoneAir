"""Contract tests proving service facades dispatch through an injected pack."""
from app.core.contracts import DomainPack, KnowledgeRepoPaths, RegexPatterns
from app.core.domain_registry import register
from app.services.product_intelligence import classify_product, match_template
from app.services.reporting import build_report
from app.services.route_resolution import resolve_origin_context, resolve_route


class _Carbon:
    def evaluate(self, **_kwargs):
        return {"totals": {}, "process_breakdown": [], "machine_breakdown": [], "activity_trace": [], "chemical_inventory": {}}


class _Product:
    def classify(self, **_kwargs): return {"owner": "product"}
    def match_template(self, **_kwargs): return {"owner": "template"}


class _Routes:
    def resolve(self, **_kwargs): return {"owner": "route"}
    def resolve_origin_context(self, **_kwargs): return {"owner": "origin"}


class _Report:
    def build(self, **_kwargs): return {"owner": "report"}


def test_domain_services_use_registered_pack_interfaces(tmp_path):
    register("dispatch-test", lambda: DomainPack(
        domain_id="dispatch-test", display_name="Dispatch Test", material_aliases={},
        regex_patterns=RegexPatterns(None, None, None), keyword_bank=[],
        origin_sensitive_process_groups=set(), transport_mode_hints=[],
        default_export_distance_km=0, default_export_mode="", chemical_factor_aliases={},
        knowledge_repo_paths=KnowledgeRepoPaths(tmp_path / "taxonomy.csv", tmp_path / "templates.csv", tmp_path / "routes.csv"),
        carbon_model=_Carbon(), product_intelligence=_Product(), route_resolver=_Routes(), report_builder=_Report(),
    ))

    try:
        assert classify_product(object(), domain="dispatch-test") == {"owner": "product"}
        assert match_template("tax", object(), domain="dispatch-test") == {"owner": "template"}
        assert resolve_route("tax", object(), default_route_id="route", domain="dispatch-test") == {"owner": "route"}
        assert resolve_origin_context(object(), domain="dispatch-test") == {"owner": "origin"}
        assert build_report({}, {}, {}, {}, domain="dispatch-test") == {"owner": "report"}
    finally:
        # Registry has no public unregistration by design; clean up the temporary
        # test-only provider so the global plugin registry remains deterministic.
        import app.core.domain_registry as registry

        registry._PROVIDERS.pop("dispatch-test", None)
        registry._PACKS.pop("dispatch-test", None)
