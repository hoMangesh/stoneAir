"""Static and behavioral validation for domain-pack implementations."""
from __future__ import annotations

import re
from dataclasses import asdict, dataclass
from typing import Any

from app.core.contracts import DomainPack


@dataclass(frozen=True)
class ValidationIssue:
    code: str
    severity: str
    message: str


@dataclass(frozen=True)
class ValidationReport:
    domain_id: str
    valid: bool
    issues: tuple[ValidationIssue, ...]

    def to_dict(self) -> dict[str, Any]:
        return {"domain_id": self.domain_id, "valid": self.valid, "issues": [asdict(issue) for issue in self.issues]}


def validate_pack(pack: DomainPack) -> ValidationReport:
    """Validate the frozen four-interface contract without domain assumptions."""
    issues: list[ValidationIssue] = []
    if not re.fullmatch(r"[a-z][a-z0-9_]{1,62}", pack.domain_id):
        issues.append(ValidationIssue("SDK001", "error", "domain_id must be lowercase snake_case."))
    if not pack.display_name.strip():
        issues.append(ValidationIssue("SDK002", "error", "display_name is required."))
    if any(key != key.strip().lower() for key in pack.material_aliases):
        issues.append(ValidationIssue("SDK003", "warning", "material aliases should use normalized lowercase keys."))
    if pack.default_export_distance_km < 0:
        issues.append(ValidationIssue("SDK004", "error", "default_export_distance_km cannot be negative."))
    if not pack.default_export_mode and pack.default_export_distance_km:
        issues.append(ValidationIssue("SDK005", "warning", "export distance has no declared transport mode."))

    try:
        classification = pack.product_intelligence.classify(signals={}, repos=None)
        if not isinstance(classification, dict):
            raise TypeError("classification must return an object")
        taxonomy_id = str((classification.get("taxonomy") or {}).get("taxonomy_id") or "SDK-SAMPLE")
        template = pack.product_intelligence.match_template(taxonomy_id=taxonomy_id, signals={}, repos=None)
        route = pack.route_resolver.resolve(taxonomy_id=taxonomy_id, signals={}, default_route_id=None, repos=None)
        origin = pack.route_resolver.resolve_origin_context(signals={}, repos=None)
        resources = pack.carbon_model.evaluate(route_steps=[], weight_g=1, origin_context=origin, repos=None)
        report = pack.report_builder.build(classification=classification, template_match=template, route=route, resources=resources)
        if not isinstance(resources, dict) or not {"totals", "activity_trace"}.issubset(resources):
            issues.append(ValidationIssue("SDK006", "error", "carbon_model must return totals and activity_trace."))
        if not isinstance(report, dict):
            issues.append(ValidationIssue("SDK007", "error", "report_builder must return an object."))
    except Exception as exc:  # SDK validation converts plugin failures into actionable results.
        issues.append(ValidationIssue("SDK008", "error", f"contract dry-run failed: {type(exc).__name__}: {exc}"))
    return ValidationReport(pack.domain_id, not any(issue.severity == "error" for issue in issues), tuple(issues))


__all__ = ["ValidationIssue", "ValidationReport", "validate_pack"]
