from pathlib import Path


def test_domain_sdk_has_no_apparel_knowledge_or_core_domain_imports():
    root = Path(__file__).resolve().parents[1] / "domain_sdk"
    forbidden = ("domain_packs.apparel", "app.services.product_intelligence", "app.services.resource_models")
    assert all(token not in path.read_text() for path in root.glob("*.py") for token in forbidden)
