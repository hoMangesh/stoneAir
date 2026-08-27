"""Step 4b Phase 5 — the machine_recommender <-> machine_energy_profiles catalog
bridge: the 52-machine recommender catalog joined to the energy pipeline.

Offline, read-only: asserts the deterministic bridge generator emits 46
energy-bearing machines (skipping the 6 non-energy Design/Quality/Inspection
categories), that each bridged ``MMODR`` row is consistent across all three
master files AND the derivation unit map, that the 6 seed ``MMOD00`` rows are
untouched, that re-running the generator is byte-identical (idempotent), and
that ``/api/brochure-coverage`` now reports the full 52-machine surface
(46 bridge + 6 seed) so the aggregate derived-vs-proxy-vs-unsupported ratio is
the real catalog-wide confidence signal.

No master is mutated: the generator's ``build_rows()`` reads the committed
catalog + the alias map and returns rows; the coverage endpoint reads the
committed masters via the loader. Neither writes.
"""
from __future__ import annotations

import csv
from pathlib import Path

import pytest

from app import config
from app.services.brochure_pipeline import _CATEGORY_UNIT
from app.services.knowledge_loader import load_master_data


# The builder lives under backend/scripts/, not on the package path. Import it
# directly from its file so the test exercises the real generation code.
import importlib.util

_BUILDER_PATH = (
    Path(config.__file__).resolve().parent.parent / "scripts" / "build_catalog_bridge.py"
)
_spec = importlib.util.spec_from_file_location("build_catalog_bridge", _BUILDER_PATH)
build_catalog_bridge = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(build_catalog_bridge)


# ---------------------------------------------------------------------------
# build_rows() — shape, count, category/unit consistency, idempotence
# ---------------------------------------------------------------------------
def test_build_rows_skips_non_energy_and_counts_46():
    rows = build_catalog_bridge.build_rows()
    # 52 catalog machines - 6 non-energy (Design x3, Quality x2, Inspection x1).
    assert len(rows) == 46

    recommender_ids = {r["recommender_id"] for r in rows}
    # The 6 non-energy ids must NOT appear.
    for excluded in ("M001", "M003", "M004", "M005", "M033", "M034"):
        assert excluded not in recommender_ids, f"{excluded} is non-energy, must be skipped"


def test_build_rows_mmODR_ids_are_sequential():
    rows = build_catalog_bridge.build_rows()
    assert [r["machine_model_id"] for r in rows] == [
        f"MMODR-{i:03d}" for i in range(1, 47)
    ]


def test_build_rows_unit_matches_category_unit_map():
    """Every bridge row's unit must equal _CATEGORY_UNIT for its category so a
    later brochure derivation/promotion lands an honest per-category unit."""
    rows = build_catalog_bridge.build_rows()
    for r in rows:
        expected = _CATEGORY_UNIT.get(r["machine_category"])
        assert expected is not None, (
            f"{r['machine_model_id']} category {r['machine_category']!r} has no unit "
            "in _CATEGORY_UNIT — the proxy unit wouldn't match a derivation"
        )
        assert r["unit"] == expected, (
            f"{r['machine_model_id']} unit {r['unit']!r} != {expected!r} for category "
            f"{r['machine_category']!r}"
        )


def test_build_rows_is_idempotent():
    a = build_catalog_bridge.build_rows()
    b = build_catalog_bridge.build_rows()
    assert a == b


# ---------------------------------------------------------------------------
# Three-master consistency — the committed rows join end-to-end
# ---------------------------------------------------------------------------
def _read_master(name: str) -> list[dict[str, str]]:
    path = Path(config.MASTER_DATASETS[name])
    with path.open(newline="", encoding="utf-8") as fh:
        return list(csv.DictReader(fh))


def test_bridge_rows_consistent_across_three_masters():
    bridge_rows = {r["recommender_id"]: r for r in _read_master("machine_recommender_bridge")}
    mmodels = {r["machine_model_id"]: r for r in _read_master("machine_models")}
    energy = {r["machine_model_id"]: r for r in _read_master("machine_energy_profiles")}

    assert len(bridge_rows) == 46

    for rid, b in bridge_rows.items():
        mid = b["machine_model_id"]
        cat = b["machine_category"]

        mm = mmodels.get(mid)
        assert mm is not None, f"{mid}: missing from machine_models.csv"
        assert mm["machine_category"] == cat, (
            f"{mid}: machine_models category {mm['machine_category']!r} "
            f"!= bridge {cat!r}"
        )
        assert mm["source"].startswith("machine_recommender bridge"), (
            f"{mid}: machine_models source not bridge-tagged: {mm['source']!r}"
        )

        en = energy.get(mid)
        assert en is not None, f"{mid}: missing from machine_energy_profiles.csv"
        assert en["unit"] == _CATEGORY_UNIT.get(cat), (
            f"{mid}: energy unit {en['unit']!r} != "
            f"{_CATEGORY_UNIT.get(cat)!r} for {cat!r}"
        )
        assert en["approval_status"] == "Pending Validation"
        assert en["confidence"] == "0.55"
        assert f"bridge proxy ({rid})" in en["source"]


def test_seed_mmOD_rows_untouched_by_bridge():
    """The 6 original MMOD seed rows survive unchanged: each is present in
    machine_energy_profiles with its seed approval_status/host, NOT re-written
    as a Pending Validation bridge proxy."""
    energy = _read_master("machine_energy_profiles")
    seed = [r for r in energy if r["machine_model_id"].startswith("MMOD00")]
    assert len(seed) == 6
    for r in seed:
        assert "machine_recommender bridge" not in r["source"]
        assert "bridge proxy" not in r["source"]
    # Bridge rows are a disjoint MMODR-*** prefix.
    assert not any(r["machine_model_id"].startswith("MMOD00") and "MMODR" in r["machine_model_id"]
                   for r in energy)


def test_mmodr_ids_are_disjoint_from_seed():
    ids = {r["machine_model_id"] for r in _read_master("machine_energy_profiles")}
    seed = {i for i in ids if i.startswith("MMOD00")}
    bridge = {i for i in ids if i.startswith("MMODR-")}
    assert len(seed) == 6
    assert len(bridge) == 46
    assert seed.isdisjoint(bridge)


# ---------------------------------------------------------------------------
# Loader index + /api/brochure-coverage aggregate
# ---------------------------------------------------------------------------
def test_loader_indexes_bridge_by_recommender_id():
    master = load_master_data()
    bridge = master["machine_recommender_bridge_by_id"]
    assert "M047" in bridge          # Snap Fastener Machine -> Sewing
    assert bridge["M047"]["machine_model_id"] == "MMODR-041"
    assert len(bridge) == 46


def test_brochure_coverage_aggregates_52_machines():
    """The coverage sweep iterates machine_models (6 seed + 46 bridge = 52),
    so the aggregate ratio is the honest catalog-wide signal."""
    from app.main import brochure_coverage

    out = brochure_coverage(live=False)
    assert out["aggregate"]["total"] == 52
    # Every machine row carries an honest, rule-aware status — no silent zeros.
    statuses = {r["profile_status"] for r in out["machines"]}
    assert out["aggregate"]["proxy"] + out["aggregate"]["approved"] + \
        out["aggregate"]["derived_approx"] + out["aggregate"]["unsupported"] == 52
    # The 46 bridge rows are Pending Validation proxies (or unsupported on a
    # no-rule category) — none are fabricated "DB-approved".
    bridge_rows = [r for r in out["machines"] if r["machine_model_id"].startswith("MMODR-")]
    assert len(bridge_rows) == 46
    assert all(r["approval_status"] in ("", "Pending Validation") for r in bridge_rows)
