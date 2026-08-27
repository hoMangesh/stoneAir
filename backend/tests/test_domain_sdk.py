from pathlib import Path

from app.core import domain_registry
from app.core.domain_registry import resolve
from domain_sdk import certify_pack, register_domain_plugin, validate_pack
from domain_sdk.scaffold import scaffold_pack
from domain_packs.sandbox.implementation import build_pack


def test_sandbox_domain_dry_run_validates_certifies_and_registers():
    pack = build_pack()

    validation = validate_pack(pack)
    certificate = certify_pack(pack)
    try:
        registered = register_domain_plugin(build_pack)

        assert validation.valid is True
        assert certificate.status == "certified"
        assert registered.domain_id == "sandbox"
        assert resolve("sandbox").display_name == "Sandbox SDK Dry Run"
    finally:
        # The registry is process-wide; a dry-run must leave built-in pack
        # discovery exactly as it was for frozen regression tests.
        domain_registry._PROVIDERS.pop("sandbox", None)
        domain_registry._PACKS.pop("sandbox", None)


def test_scaffold_creates_non_overwriting_pack_template(tmp_path: Path):
    target = scaffold_pack(domain_id="new_domain", display_name="New Domain", output=tmp_path)

    assert target.joinpath("__init__.py").exists()
    assert "register_domain_plugin" in target.joinpath("__init__.py").read_text()
    assert "DomainPack" in target.joinpath("implementation.py").read_text()
