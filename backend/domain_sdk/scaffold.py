"""Developer tooling to scaffold a minimal independently owned domain pack."""
from __future__ import annotations

import argparse
from pathlib import Path


_INIT_TEMPLATE = '''"""{display_name} domain pack."""
from app.core.contracts import DomainPack
from domain_sdk import register_domain_plugin
from .implementation import build_pack

pack = register_domain_plugin(build_pack)
__all__ = ["pack"]
'''

_IMPLEMENTATION_TEMPLATE = '''"""Replace synthetic SDK examples with domain-owned knowledge and rules."""
from pathlib import Path
from app.core.contracts import DomainPack, KnowledgeRepoPaths, RegexPatterns

class ProductIntelligence:
    def classify(self, *, signals, repos=None):
        return {{"taxonomy": {{"taxonomy_id": "{domain_upper}-SAMPLE"}}, "confidence": 1.0}}
    def match_template(self, *, taxonomy_id, signals, repos=None):
        return {{"template": {{"default_route_id": "{domain_upper}-ROUTE"}}}}
class RouteResolver:
    def resolve(self, *, taxonomy_id, signals, default_route_id, repos=None): return {{"route_id": default_route_id or "{domain_upper}-ROUTE"}}
    def resolve_origin_context(self, *, signals, repos=None): return None
class CarbonModel:
    def evaluate(self, *, route_steps, weight_g, origin_context=None, repos=None): return {{"totals": {{}}, "activity_trace": []}}
class ReportBuilder:
    def build(self, *, classification, template_match, route, resources): return {{"classification": classification, "route": route, "impact": resources["totals"]}}

def build_pack():
    root = Path(__file__).parent
    return DomainPack(domain_id="{domain_id}", display_name="{display_name}", material_aliases={{}}, regex_patterns=RegexPatterns(None, None, None), keyword_bank=[], origin_sensitive_process_groups=set(), transport_mode_hints=[], default_export_distance_km=0, default_export_mode="", chemical_factor_aliases={{}}, knowledge_repo_paths=KnowledgeRepoPaths(root / "taxonomy.csv", root / "templates.csv", root / "routes.csv"), carbon_model=CarbonModel(), product_intelligence=ProductIntelligence(), route_resolver=RouteResolver(), report_builder=ReportBuilder())
'''


def scaffold_pack(*, domain_id: str, display_name: str, output: Path) -> Path:
    """Create a minimal pack only when its target does not already exist."""
    target = output / domain_id
    if target.exists():
        raise FileExistsError(f"refusing to overwrite existing pack: {target}")
    target.mkdir(parents=True)
    target.joinpath("__init__.py").write_text(_INIT_TEMPLATE.format(display_name=display_name))
    target.joinpath("implementation.py").write_text(_IMPLEMENTATION_TEMPLATE.format(domain_id=domain_id, domain_upper=domain_id.upper(), display_name=display_name))
    return target


def main() -> None:
    parser = argparse.ArgumentParser(description="Scaffold a domain SDK pack")
    parser.add_argument("domain_id")
    parser.add_argument("display_name")
    parser.add_argument("--output", type=Path, default=Path("domain_packs"))
    args = parser.parse_args()
    print(scaffold_pack(domain_id=args.domain_id, display_name=args.display_name, output=args.output))


if __name__ == "__main__":
    main()
