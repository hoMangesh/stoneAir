"""Self-contained synthetic knowledge and interface implementations for Dummy."""
from __future__ import annotations

from pathlib import Path

from app.core.contracts import DomainPack, KnowledgeRepoPaths, RegexPatterns


class DummyProductIntelligence:
    def classify(self, *, signals, repos=None):
        return {
            "taxonomy": {"taxonomy_id": "DUMMY-001", "level_1_domain": "Dummy"},
            "confidence": 1.0,
            "match_score": 1.0,
            "alternatives": [],
        }

    def match_template(self, *, taxonomy_id, signals, repos=None):
        return {
            "template": {"template_id": "DUMMY-TEMPLATE", "template_name": "Dummy Product", "default_route_id": "DUMMY-ROUTE"},
            "resolved_weight_g": 1,
            "resolved_gsm": None,
            "material_blend": "dummy",
        }


class DummyRouteResolver:
    def resolve(self, *, taxonomy_id, signals, default_route_id, repos=None):
        return {"route_id": default_route_id or "DUMMY-ROUTE", "is_fallback": False, "candidates_seen": 1}

    def resolve_origin_context(self, *, signals, repos=None):
        return None


class DummyReportBuilder:
    def build(self, *, classification, template_match, route, resources):
        return {"domain": "dummy", "classification": classification, "route": route, "impact": resources["totals"]}


class DummyCarbonModel:
    def evaluate(self, *, route_steps, weight_g, origin_context=None, repos=None):
        return {
            "totals": {"energy_kwh": 0.0, "water_l": 0.0, "carbon_kgco2e": 0.0},
            "process_breakdown": [],
            "machine_breakdown": [],
            "activity_trace": [],
            "chemical_inventory": {},
        }


def build_pack() -> DomainPack:
    root = Path(__file__).resolve().parent
    return DomainPack(
        domain_id="dummy",
        display_name="Dummy Domain (contract validation only)",
        material_aliases={},
        regex_patterns=RegexPatterns(None, None, None),
        keyword_bank=[],
        origin_sensitive_process_groups=set(),
        transport_mode_hints=[],
        default_export_distance_km=0,
        default_export_mode="",
        chemical_factor_aliases={},
        knowledge_repo_paths=KnowledgeRepoPaths(root / "taxonomy.csv", root / "templates.csv", root / "routes.csv"),
        carbon_model=DummyCarbonModel(),
        product_intelligence=DummyProductIntelligence(),
        route_resolver=DummyRouteResolver(),
        report_builder=DummyReportBuilder(),
    )
