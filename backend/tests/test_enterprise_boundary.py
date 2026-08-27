from pathlib import Path


def test_enterprise_control_plane_has_no_apparel_or_twin_domain_logic():
    root = Path(__file__).resolve().parents[1] / "app"
    files = [root / "core" / "enterprise.py", root / "services" / "enterprise_operations.py"]
    forbidden = ("domain_packs.apparel", "app.services.product_intelligence", "app.core.twin")
    assert all(token not in path.read_text() for path in files for token in forbidden)
