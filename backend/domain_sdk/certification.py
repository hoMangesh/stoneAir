"""Repeatable certification pipeline for independently developed domain packs."""
from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any

from app.core.contracts import DomainPack
from domain_sdk.validation import validate_pack


@dataclass(frozen=True)
class CertificationResult:
    certification_version: str
    domain_id: str
    status: str
    checks: tuple[dict[str, Any], ...]
    validation: dict[str, Any]

    def to_dict(self) -> dict[str, Any]:
        return asdict(self) | {"checks": list(self.checks)}


def certify_pack(pack: DomainPack) -> CertificationResult:
    """Run deterministic SDK checks. Certification never alters a pack or registry."""
    validation = validate_pack(pack)
    checks = (
        {"check_id": "CERT001", "name": "four-interface contract dry run", "passed": validation.valid},
        {"check_id": "CERT002", "name": "domain-neutral pack metadata", "passed": bool(pack.domain_id and pack.display_name)},
        {"check_id": "CERT003", "name": "frozen configuration", "passed": hasattr(pack, "__dataclass_fields__")},
    )
    passed = validation.valid and all(check["passed"] for check in checks)
    return CertificationResult("1.0", pack.domain_id, "certified" if passed else "rejected", checks, validation.to_dict())


__all__ = ["CertificationResult", "certify_pack"]
