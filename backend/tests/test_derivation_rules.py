"""Step 4b Phase 2 — per-category derivation rules.

Offline tests (no network): synthetic brochure snippets per category assert the
right physics (batch×cycle for dyeing, per-garment for sewing, feed×area for
cutting, area-throughput for printing) instead of the generic ``kW ÷ kg/h``
shape. Covers the dispatcher path (``_derive_from_text(text, category)``) and the
review path (``extract_brochure``), plus the kept-green legacy contract: a
no-category call still returns the mass-rate shape.
"""
from app.services import brochure_discovery as bd
from app.services import brochure_pipeline as bp
from app.services import derivation_rules as dr


# A minimal parse adapter the rules expect (the same I/O helpers brochure_pipeline
# uses), so tests exercise the real regexes, not a mock.
class _Parse:
    power = staticmethod(bp._parse_power)
    throughput_kg_per_h = staticmethod(bp._parse_throughput_kg_per_h)


# ---------------------------------------------------------------------------
# mass-rate (Ring Frame / Circular Knitting) — the legacy shape, kept honest
# ---------------------------------------------------------------------------
def test_mass_rate_ring_frame():
    r = dr.derive_for_category("Ring Frame", "Installed power: 7.5 kW, Throughput: 30 kg/h", _Parse)
    assert r is not None
    assert r.rule_name == "mass-rate"
    assert r.unit == "kWh/kg"
    assert r.kwh_per_unit == round(7.5 / 30.0, 4)
    assert r.confidence == 0.8


def test_mass_rate_returns_none_without_power():
    r = dr.derive_for_category("Ring Frame", "Throughput: 30 kg/h, no power", _Parse)
    assert r is None


# ---------------------------------------------------------------------------
# batch-cycle (Jet Dyeing / Washing) — kW × cycle ÷ batch_kg
# ---------------------------------------------------------------------------
def test_batch_cycle_jet_dyeing():
    text = "Thies iMaster H2O. Installed power 45 kW. Max load 250 kg. Cycle time 60 min."
    r = dr.derive_for_category("Jet Dyeing Machine", text, _Parse)
    assert r is not None
    assert r.rule_name == "batch-cycle"
    assert r.unit == "kWh/kg fabric"
    # 45 kW × 1 h ÷ 250 kg = 0.18
    assert r.kwh_per_unit == round(45.0 * 1.0 / 250.0, 4)
    assert r.confidence == 0.7


def test_batch_cycle_minutes_normalised_to_hours():
    # 90 min = 1.5 h; 0.18 kW is intentionally tiny so the shape, not magnitude, is tested.
    text = "Installed power 0.18 kW. Max load 1 kg. Cycle time 90 min."
    r = dr.derive_for_category("Washing Machine", text, _Parse)
    assert r is not None
    assert r.rule_name == "batch-cycle"
    assert r.kwh_per_unit == round(0.18 * 1.5 / 1.0, 4)


def test_batch_cycle_falls_back_to_mass_rate_when_only_kg_h():
    # A dyeing brochure that only quotes an effective kg/h: must still derive via mass-rate.
    text = "Installed power: 18.0 kW, Throughput: 120 kg/h"
    r = dr.derive_for_category("Jet Dyeing Machine", text, _Parse)
    assert r is not None
    assert r.rule_name == "mass-rate"
    assert r.kwh_per_unit == round(18.0 / 120.0, 4)


# ---------------------------------------------------------------------------
# per-garment (Lockstitch / Sewing) — kW ÷ (stitches/min × 60)
# ---------------------------------------------------------------------------
def test_per_garment_lockstitch_with_stitches_per_min():
    text = "Juki DDL-8700. Motor 0.55 kW. Max sewing speed 4000 stitches/min."
    r = dr.derive_for_category("Lockstitch Machine", text, _Parse)
    assert r is not None
    assert r.rule_name == "per-garment"
    assert r.unit == "kWh/garment"
    assert r.kwh_per_unit == round(0.55 / (4000.0 * 60), 6)
    assert r.confidence == 0.55


def test_per_garment_falls_back_to_mass_rate_with_kg_h():
    text = "0.55 kW. Throughput 8 kg/h."  # an effective mass rate quoted
    r = dr.derive_for_category("Lockstitch Machine", text, _Parse)
    assert r is not None
    assert r.rule_name == "mass-rate"


def test_sewing_alias_routes_to_per_garment():
    # The broader machine_recommender category 'Sewing' must alias to Lockstitch.
    text = "0.4 kW, 5000 stitches/min."
    r = dr.derive_for_category("Sewing", text, _Parse)
    assert r is not None
    assert r.rule_name == "per-garment"


# ---------------------------------------------------------------------------
# feed-area (CNC Cutter / Spreading) — kW ÷ (speed × width × 3600s/hour)
# ---------------------------------------------------------------------------
def test_feed_area_cnc_cutter():
    text = "Gerber GTXL. Cutting speed 30 m/min, working width 1.8 m. Installed power 2.2 kW."
    r = dr.derive_for_category("CNC Fabric Cutter", text, _Parse)
    assert r is not None
    assert r.rule_name == "feed-area"
    assert r.unit == "kWh/m²"
    # 30 m/min × 1.8 m × 60 = 3240 m²/h ; 2.2 / 3240
    assert r.kwh_per_unit == round(2.2 / (30.0 * 1.8 * 60.0), 6)


def test_cutting_alias_routes_to_feed_area():
    text = "1.5 kW, cutting speed 20 m/min, fabric width 1.6 m."
    r = dr.derive_for_category("Cutting", text, _Parse)
    assert r is not None
    assert r.rule_name == "feed-area"


def test_feed_area_bogus_kg_h_only_does_not_use_kg_h_shape():
    # A cutter brochure that only quotes a kg/h: not the feed-area formula — the
    # rule degrades to mass-rate, which is the honest fallback, NOT feed-area.
    text = "2.2 kW. Throughput 12 kg/h."  # no speed/width
    r = dr.derive_for_category("CNC Fabric Cutter", text, _Parse)
    assert r is not None
    assert r.rule_name == "mass-rate"
    assert "kW /" in r.basis and "kg/h" in r.basis


# ---------------------------------------------------------------------------
# area-throughput (Printing) — kW ÷ m²/h
# ---------------------------------------------------------------------------
def test_area_throughput_printing():
    text = "MS Printing. Installed power 12 kW. Throughput 80 m2/h."
    r = dr.derive_for_category("Printing Machine", text, _Parse)
    assert r is not None
    assert r.rule_name == "area-throughput"
    assert r.unit == "kWh/m²"
    assert r.kwh_per_unit == round(12.0 / 80.0, 6)


# ---------------------------------------------------------------------------
# thermal (Stenter / Ironing / Drying)
# ---------------------------------------------------------------------------
def test_thermal_stenter_with_kg_h_uses_mass_rate():
    text = "Stenter. Installed power 30 kW. Throughput 100 kg/h."
    r = dr.derive_for_category("Stenter Machine", text, _Parse)
    assert r is not None
    assert r.rule_name == "mass-rate"


# ---------------------------------------------------------------------------
# unknown — best-effort, never silent proxy/zero
# ---------------------------------------------------------------------------
def test_unknown_category_best_effort_demotes_confidence():
    text = "Mystery 10 kW machine, 60 kg/h."
    r = dr.derive_for_category("Teleporter", text, _Parse)
    assert r is not None
    assert r.rule_name == "unknown-best-effort"
    assert r.kwh_per_unit == round(10.0 / 60.0, 4)
    assert r.confidence == 0.35  # demoted — mass-rate on an unknown rule is a guess


def test_unknown_category_power_only_flags_unsupported():
    text = "Mystery 8 kW machine, no throughput."
    r = dr.derive_for_category("Teleporter", text, _Parse)
    assert r is not None
    assert r.rule_name == "unknown-power-only"
    assert r.kwh_per_unit == 0.0
    assert r.confidence == 0.2


def test_unknown_category_no_data_returns_none():
    r = dr.derive_for_category("Teleporter", "no useful numbers", _Parse)
    assert r is None


# ---------------------------------------------------------------------------
# Dispatcher never raises (regex/parse robustness)
# ---------------------------------------------------------------------------
def test_dispatcher_never_raises_on_garbage():
    # Whatever the text, derive_for_category must not raise.
    out = dr.derive_for_category("Jet Dyeing Machine", "<\x00null\xff>", _Parse)
    assert out is None or isinstance(out, dr.Result)


# ---------------------------------------------------------------------------
# _derive_from_text threading — the live ladder's contract
# ---------------------------------------------------------------------------
def test_derive_from_text_with_category_uses_batch_cycle():
    text = "Installed power 45 kW. Max load 250 kg. Cycle time 60 min."
    kwh, power, throughput, basis = bd._derive_from_text(text, "Jet Dyeing Machine")
    assert power == 45.0
    assert kwh == round(45.0 * 1.0 / 250.0, 4)
    assert throughput is None  # batch-cycle doesn't surface kg/h
    assert "250" in basis and "60" in basis


def test_derive_from_text_legacy_no_category_still_mass_rate():
    # Locked backward-compat: a no-category call keeps the mass-rate shape.
    text = "Installed power: 18.0 kW\nThroughput: 120 kg/h\n"
    kwh, power, throughput, basis = bd._derive_from_text(text)
    assert power == 18.0
    assert throughput == 120.0
    assert kwh == round(18.0 / 120.0, 4)


def test_derive_from_text_unknown_power_only_yields_none_kwh():
    # An unknown-category, power-only rule must not emit a fake kWh downstream.
    text = "Mystery 8 kW machine, no throughput."
    kwh, power, throughput, basis = bd._derive_from_text(text, "Teleporter")
    assert kwh is None
    assert power == 8.0
    assert "needs rule" in basis or "unsupported" in basis


# ---------------------------------------------------------------------------
# extract_brochure — review path agrees with the live ladder
# ---------------------------------------------------------------------------
def test_extract_brochure_ring_frame_mass_rate():
    r = bp.extract_brochure("MMOD003", "Installed power: 7.5 kW, Throughput: 30 kg/h")
    d = r["derivation"]
    assert d["rule"] == "mass-rate"
    assert d["derived_kwh_per_unit"] == round(7.5 / 30.0, 4)
    assert d["unit"] == "kWh/kg yarn"


def test_extract_brochure_jet_dyeing_uses_batch_cycle():
    text = "Thies iMaster H2O. Installed power 45 kW. Max load 250 kg. Cycle time 60 min."
    r = bp.extract_brochure("MMOD001", text)
    d = r["derivation"]
    assert d["rule"] == "batch-cycle"
    assert d["derived_kwh_per_unit"] == round(45.0 * 1.0 / 250.0, 4)
    assert d["unit"] == "kWh/kg fabric"


def test_extract_brochure_jet_dyeing_kg_h_only_falls_back_to_mass_rate():
    # The legacy Thies test shape: kg/h present, no batch/cycle -> mass-rate.
    r = bp.extract_brochure("MMOD001", "Installed power: 18.0 kW, Throughput: 120 kg/h")
    d = r["derivation"]
    assert d["rule"] == "mass-rate"
    assert d["derived_kwh_per_unit"] == round(18.0 / 120.0, 4)
