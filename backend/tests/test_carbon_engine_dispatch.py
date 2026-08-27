from app.core.carbon_engine import evaluate
from app.core.contracts import DomainPack, KnowledgeRepoPaths, RegexPatterns


class _Model:
    def __init__(self):
        self.called_with = None

    def evaluate(self, *, route_steps, weight_g, origin_context=None, repos=None):
        self.called_with = (route_steps, weight_g, origin_context, repos)
        return {
            "totals": {},
            "process_breakdown": [],
            "machine_breakdown": [],
            "activity_trace": [],
            "chemical_inventory": {},
        }


class _Product:
    def classify(self, **_kwargs): return {}
    def match_template(self, **_kwargs): return {}


class _Routes:
    def resolve(self, **_kwargs): return {}
    def resolve_origin_context(self, **_kwargs): return None


class _Report:
    def build(self, **_kwargs): return {}


def test_carbon_engine_delegates_to_the_pack_model(tmp_path):
    model = _Model()
    pack = DomainPack(
        domain_id="test",
        display_name="Test",
        material_aliases={},
        regex_patterns=RegexPatterns(None, None, None),
        keyword_bank=[],
        origin_sensitive_process_groups=set(),
        transport_mode_hints=[],
        default_export_distance_km=0,
        default_export_mode="",
        chemical_factor_aliases={},
        knowledge_repo_paths=KnowledgeRepoPaths(tmp_path / "taxonomy.csv", tmp_path / "templates.csv", tmp_path / "routes.csv"),
        carbon_model=model,
        product_intelligence=_Product(),
        route_resolver=_Routes(),
        report_builder=_Report(),
    )
    repos = {"source": "test"}
    result = evaluate(pack=pack, route_steps=[{"process_name": "step"}], weight_g=100, origin_context={"origin": "X"}, repos=repos)

    assert result["totals"] == {}
    assert model.called_with == ([{"process_name": "step"}], 100, {"origin": "X"}, repos)
