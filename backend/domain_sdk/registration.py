"""Validated registration adapter for third-party domain packs."""
from __future__ import annotations

from collections.abc import Callable

from app.core.contracts import DomainPack
from app.core.domain_registry import register
from domain_sdk.validation import validate_pack


class PluginRegistrationError(ValueError):
    pass


def register_domain_plugin(provider: Callable[[], DomainPack]) -> DomainPack:
    """Materialize, validate, and register one pack through the frozen registry."""
    pack = provider()
    report = validate_pack(pack)
    if not report.valid:
        details = "; ".join(issue.message for issue in report.issues if issue.severity == "error")
        raise PluginRegistrationError(f"cannot register {pack.domain_id}: {details}")
    register(pack.domain_id, lambda: pack)
    return pack


__all__ = ["PluginRegistrationError", "register_domain_plugin"]
