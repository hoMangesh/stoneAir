"""Self-contained behavior used to validate the domain SDK onboarding flow."""
from __future__ import annotations

from pathlib import Path

from app.core.contracts import DomainPack, KnowledgeRepoPaths, RegexPatterns


class SandboxProductIntelligence:
    def classify(self, *, signals, repos=None):
        return {"taxonomy": {"taxonomy_id": "SANDBOX-001", "level_1_domain": "Sandbox"}, "confidence": 1.0, "alternatives": []}

    def match_template(self, *, taxonomy_id, signals, repos=None):
        return {"template": {"template_id": "SANDBOX-TEMPLATE", "default_route_id": "SANDBOX-ROUTE"}}


class SandboxRouteResolver:
    def resolve(self, *, taxonomy_id, signals, default_route_id, repos=None):
        return {"route_id": default_route_id or "SANDBOX-ROUTE", "is_fallback": False}

    def resolve_origin_context(self, *, signals, repos=None):
        return None


class SandboxCarbonModel:
    def evaluate(self, *, route_steps, weight_g, origin_context=None, repos=None):
        return {"totals": {"energy_kwh": 0.0, "water_l": 0.0, "carbon_kgco2e": 0.0}, "activity_trace": [], "machine_breakdown": [], "process_breakdown": [], "chemical_inventory": {}}


class SandboxReportBuilder:
    def build(self, *, classification, template_match, route, resources):
        return {"domain": "sandbox", "classification": classification, "route": route, "impact": resources["totals"]}


def build_pack() -> DomainPack:
    root = Path(__file__).resolve().parent
    return DomainPack(
        domain_id="sandbox",
        display_name="Sandbox SDK Dry Run",
        material_aliases={},
        regex_patterns=RegexPatterns(None, None, None),
        keyword_bank=[],
        origin_sensitive_process_groups=set(),
        transport_mode_hints=[],
        default_export_distance_km=0,
        default_export_mode="",
        chemical_factor_aliases={},
        knowledge_repo_paths=KnowledgeRepoPaths(root / "taxonomy.csv", root / "templates.csv", root / "routes.csv"),
        carbon_model=SandboxCarbonModel(),
        product_intelligence=SandboxProductIntelligence(),
        route_resolver=SandboxRouteResolver(),
        report_builder=SandboxReportBuilder(),
    )
