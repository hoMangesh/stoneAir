"""Apparel implementations of the stable product, route, and report contracts."""
from __future__ import annotations


class ApparelProductIntelligence:
    def classify(self, *, signals, repos=None):
        from app.services.product_intelligence import _classify_product

        return _classify_product(signals, domain_id="apparel", repos=repos)

    def match_template(self, *, taxonomy_id, signals, repos=None):
        from app.services.product_intelligence import _match_template

        return _match_template(taxonomy_id, signals, repos=repos)


class ApparelRouteResolver:
    def __init__(self, origin_sensitive_process_groups: set[str]):
        self._origin_sensitive_process_groups = origin_sensitive_process_groups

    def resolve(self, *, taxonomy_id, signals, default_route_id, repos=None):
        from app.services.route_resolution import _resolve_route

        return _resolve_route(taxonomy_id, signals, default_route_id=default_route_id, repos=repos)

    def resolve_origin_context(self, *, signals, repos=None):
        from app.services.route_resolution import _resolve_origin_context

        return _resolve_origin_context(
            signals,
            repos=repos,
            origin_sensitive_process_groups=self._origin_sensitive_process_groups,
        )


class ApparelReportBuilder:
    def build(self, *, classification, template_match, route, resources):
        from app.services.reporting import _build_report

        return _build_report(classification, template_match, route, resources)


__all__ = ["ApparelProductIntelligence", "ApparelRouteResolver", "ApparelReportBuilder"]
