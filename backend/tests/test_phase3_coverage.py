"""Step 4b Phase 3 — coverage sweep + tier-aware activity confidence.

Offline tests (no network): the /api/brochure-coverage handler returns one row
per catalog machine with an aggregate derived-vs-proxy-vs-unsupported ratio that
matches the machine count; the finder's source tier propagates into the carbon
activity-row confidence (manufacturer raises, proxy middles, demo seed demotes).
"""
from app.services import machine_intelligence as mi
from app.services import source_tier
from app.services.source_tier import (
    TIER_DEMO_SEED,
    TIER_DEMO_SEED_ST,
    TIER_MANUFACTURER,
    TIER_MANUFACTURER_ST,
    TIER_NONE,
    TIER_NONE_ST,
    TIER_PROXY,
    TIER_PROXY_ST,
)


# ---------------------------------------------------------------------------
# /api/brochure-coverage — sweep over the CURRENT (6-machine) catalog
# ---------------------------------------------------------------------------
def test_coverage_returns_one_row_per_catalog_machine(monkeypatch):
    # Force the lru_cache to the on-disk master (no live network).
    from app.services.knowledge_loader import load_master_data
    load_master_data.cache_clear()

    from app.main import brochure_coverage
    out = brochure_coverage(live=False)

    master = load_master_data()
    n_models = len(master["datasets"]["machine_models"])
    assert len(out["machines"]) == n_models
    assert out["aggregate"]["total"] == n_models
    # Offline: nothing is brochure-approved yet, so approved + derived_approx == 0.
    assert out["aggregate"]["approved"] == 0
    assert out["aggregate"]["derived_approx"] == 0
    # Every current catalog category has a derivation rule -> unsupported == 0.
    assert out["aggregate"]["unsupported"] == 0
    # proxy absorbs the rest.
    assert out["aggregate"]["proxy"] == n_models
    assert out["aggregate"]["ratio_approved"] == 0.0


def test_coverage_row_shape_carries_tier_and_basis():
    from app.services.knowledge_loader import load_master_data
    load_master_data.cache_clear()
    from app.main import brochure_coverage
    out = brochure_coverage(live=False)
    row = out["machines"][0]
    for key in (
        "machine_model_id", "manufacturer", "model", "machine_category",
        "process", "profile_status", "source_tier", "source_tier_label",
        "derivation_basis", "current_kwh", "current_unit", "approval_status",
        "rule_supported",
    ):
        assert key in row, f"missing key {key}"
    assert row["profile_status"] in (
        source_tier.COVERAGE_STATUS_APPROVED,
        source_tier.COVERAGE_STATUS_DERIVED_APPROX,
        source_tier.COVERAGE_STATUS_PROXY,
        source_tier.COVERAGE_STATUS_UNSUPPORTED,
    )


def test_coverage_flags_demo_seed_tier_on_thies_seed():
    # MMOD001's persisted profile is the explicitly-not-authentic demo seed.
    from app.services.knowledge_loader import load_master_data
    load_master_data.cache_clear()
    from app.main import brochure_coverage
    out = brochure_coverage(live=False)
    thies = next(r for r in out["machines"] if r["machine_model_id"] == "MMOD001")
    assert thies["source_tier"] == TIER_DEMO_SEED


def test_coverage_live_opt_in_does_not_break_offline_default(monkeypatch):
    # The endpoint must stay offline by default (no network); live is opt-in.
    import app.services.brochure_discovery as bd

    def _no_live(*_a, **_k):
        raise AssertionError("live discovery must not run in offline coverage mode")
    monkeypatch.setattr(bd, "discover_energy", _no_live)

    from app.services.knowledge_loader import load_master_data
    load_master_data.cache_clear()
    from app.main import brochure_coverage
    out = brochure_coverage(live=False)
    assert out["live"] is False
    # No row should have been upgraded to a derived status offline.
    assert all(r["profile_status"] != source_tier.COVERAGE_STATUS_DERIVED_APPROX for r in out["machines"])


# ---------------------------------------------------------------------------
# /api/machine-intelligence — coverage ratio surfaced on the summary
# ---------------------------------------------------------------------------
def test_machine_intelligence_summary_has_brochure_coverage():
    from app.services.knowledge_loader import load_master_data
    load_master_data.cache_clear()
    summary = mi.machine_intelligence_summary()
    coverage = summary["summary"]["brochure_coverage"]
    master = load_master_data()
    assert coverage["total"] == len(master["datasets"]["machine_models"])
    assert coverage["approved"] + coverage["derived_approx"] + coverage["proxy"] + coverage["unsupported"] == coverage["total"]
    expected_ratio = round(coverage["approved"] + coverage["derived_approx"], 3) if coverage["total"] else 0.0
    assert coverage["ratio_approved"] == expected_ratio


# ---------------------------------------------------------------------------
# source_tier — the tier-from-profile mapping (offline, master-derived)
# ---------------------------------------------------------------------------
def test_tier_approved_for_brochure_approved_profile():
    tier = source_tier.source_tier_from_profile({
        "approval_status": "Brochure Approved",
        "source": "Brochure-derived: Thies iMaster H2O official PDF",
    })
    assert tier.tier == TIER_MANUFACTURER
    assert tier.confidence_ceiling == 0.8


def test_tier_proxy_for_pending_validation():
    tier = source_tier.source_tier_from_profile({
        "approval_status": "Pending Validation",
        "source": "KG V2 Circular Knitting Machine proxy",
    })
    assert tier.tier == TIER_PROXY


def test_tier_demo_seed_for_not_authentic_flag():
    tier = source_tier.source_tier_from_profile({
        "approval_status": "Pending Brochure Review",
        "source": "Demo seed (18kW/120kg/h) — NOT authentic; pending real Thies iMaster H2O brochure",
    })
    assert tier.tier == TIER_DEMO_SEED


def test_tier_none_when_no_profile():
    tier = source_tier.source_tier_from_profile(None)
    assert tier.tier == TIER_NONE


# ---------------------------------------------------------------------------
# adjust_activity_confidence — the activity-row mapping
# ---------------------------------------------------------------------------
def test_adjust_confidence_manufacturer_raises_to_l2():
    adjusted, label = source_tier.adjust_activity_confidence(0.5, TIER_MANUFACTURER_ST)
    assert adjusted == 0.7  # lifted from middling proxy toward the approved ceiling
    assert label == TIER_MANUFACTURER_ST.label


def test_adjust_confidence_manufacturer_never_exceeds_0_8():
    adjusted, _ = source_tier.adjust_activity_confidence(0.95, TIER_MANUFACTURER_ST)
    assert adjusted == 0.8


def test_adjust_confidence_proxy_caps_at_l4():
    adjusted, label = source_tier.adjust_activity_confidence(0.7, TIER_PROXY_ST)
    assert adjusted == 0.55
    assert label == TIER_PROXY_ST.label


def test_adjust_confidence_demo_seed_demotes_to_l5():
    adjusted, _ = source_tier.adjust_activity_confidence(0.55, TIER_DEMO_SEED_ST)
    assert adjusted == 0.30  # L5 — explicitly flagged not-authentic


def test_adjust_confidence_none_demotes():
    adjusted, _ = source_tier.adjust_activity_confidence(0.5, TIER_NONE_ST)
    assert adjusted == 0.30


# ---------------------------------------------------------------------------
# Tier-aware confidence on a real activity row (e2e, offline)
# ---------------------------------------------------------------------------
def test_estimate_resources_activity_row_carries_source_tier():
    from app.services.document_intelligence import extract_document_signals
    from app.services.product_intelligence import classify_product, match_template
    from app.services.manufacturing_reconstruction import reconstruct_route
    from app.services.resource_models import estimate_resources
    from app.services.knowledge_loader import load_master_data
    load_master_data.cache_clear()

    sig = extract_document_signals(
        "cotton tee", [], bom_components=[{"material": "cotton", "percent": 100, "weight_g": 215, "origin": "India"}],
        declared_origin="India",
    )
    cls = classify_product(sig)
    tm = match_template(str(cls["taxonomy"]["taxonomy_id"]), sig)
    route = reconstruct_route(str(tm["template"]["default_route_id"]))
    res = estimate_resources(route["steps"], int(tm["resolved_weight_g"]))

    electricity_rows = [a for a in res["activity_trace"] if a.get("activity_type") == "Electricity"
                        and a.get("machine_model_id") not in (None, "FALLBACK")]
    assert electricity_rows, "expected machine electricity activity rows"
    # Every machine activity row must carry a non-empty source_tier now.
    assert all(a.get("source_tier") for a in electricity_rows)
    assert all(a.get("source_tier_label") for a in electricity_rows)
    # A KG-proxy machine (e.g. Rieter G 38 / Mayer & Cie) must report proxy tier + L4 cap.
    proxy_rows = [a for a in electricity_rows if a.get("source_tier") == TIER_PROXY]
    assert proxy_rows
    assert all(a["confidence"]["percent"] <= 55.0 for a in proxy_rows)


def test_estimate_resources_thies_demo_seed_demoted_to_l5():
    from app.services.document_intelligence import extract_document_signals
    from app.services.product_intelligence import classify_product, match_template
    from app.services.manufacturing_reconstruction import reconstruct_route
    from app.services.resource_models import estimate_resources
    from app.services.knowledge_loader import load_master_data
    load_master_data.cache_clear()

    sig = extract_document_signals(
        "cotton tee", [], bom_components=[{"material": "cotton", "percent": 100, "weight_g": 215, "origin": "India"}],
        declared_origin="India",
    )
    cls = classify_product(sig)
    tm = match_template(str(cls["taxonomy"]["taxonomy_id"]), sig)
    route = reconstruct_route(str(tm["template"]["default_route_id"]))
    res = estimate_resources(route["steps"], int(tm["resolved_weight_g"]))

    thies_rows = [a for a in res["activity_trace"]
                  if a.get("activity_type") == "Electricity" and "Thies" in (a.get("machine_model") or "")]
    assert thies_rows
    for row in thies_rows:
        assert row["source_tier"] == TIER_DEMO_SEED
        assert row["confidence"]["percent"] <= 30.0  # L5 — the flagged demo seed
