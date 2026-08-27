from pathlib import Path


def test_reasoning_core_has_no_apparel_dependency():
    core = Path(__file__).resolve().parents[1] / "app" / "core"
    forbidden = "domain_packs.apparel"
    offenders = [path for path in core.glob("*.py") if forbidden in path.read_text()]
    assert offenders == []
