"""Step 4b Phase 4 — dynamic unknown-category handling (self-improving, never silent).

Offline tests (no network, no real-master mutation): a machine whose category
has no derivation rule, but whose brochure text yields a parseable power figure,
records a best-effort/no-rule observation into machine_spec_extractions.csv
(conf 0.35, "Needs Derivation Rule"), falls to a lowest-confidence derivation
(not None, not a high-conf proxy), and surfaces in brochure_review_summary with
the actionable next-action "Author a derivation rule for {category}".

All writes point at a TEMP COPY of the master CSVs so the repo master is never
mutated by the suite.
"""
from __future__ import annotations

import csv
import shutil
import tempfile
from pathlib import Path
from unittest.mock import patch

import pytest

from app.services import brochure_discovery as bd
from app.services import brochure_pipeline as bp
from app.services import knowledge_loader
from app.services import knowledge_loader as kl
from app import config


# ---------------------------------------------------------------------------
# Fixture: redirect the CSV writers + the loader cache at a temp master copy.
# The writer (bp._SPEC_EXTRACTIONS_CSV) AND the reader must both point at the
# temp copy. The loader does ``from app.config import MASTER_DATASETS`` so it
# holds its own binding ``knowledge_loader.MASTER_DATASETS`` (originally the SAME
# dict object as config.MASTER_DATASETS). We replace BOTH bindings with a fresh
# copy of the dict whose "machine_spec_extractions" path is the temp file; the
# original is restored automatically by monkeypatch on teardown.
# ---------------------------------------------------------------------------
def _temp_spec_extractions_csv() -> Path:
    tmp = Path(tempfile.mkdtemp()) / "machine_spec_extractions.csv"
    shutil.copy(bp._SPEC_EXTRACTIONS_CSV, tmp)
    return tmp


def _redirect_spec_extractions(monkeypatch, tmp: Path) -> None:
    monkeypatch.setattr(bp, "_SPEC_EXTRACTIONS_CSV", tmp)
    redirected = dict(config.MASTER_DATASETS)
    redirected["machine_spec_extractions"] = tmp
    monkeypatch.setattr(config, "MASTER_DATASETS", redirected)
    monkeypatch.setattr(kl, "MASTER_DATASETS", redirected)
    knowledge_loader.load_master_data.cache_clear()


@pytest.fixture()
def _temp_spec_csv(monkeypatch):
    tmp = _temp_spec_extractions_csv()
    _redirect_spec_extractions(monkeypatch, tmp)
    yield tmp
    shutil.rmtree(tmp.parent, ignore_errors=True)


# ---------------------------------------------------------------------------
# record_unsupported_observation — the writer
# ---------------------------------------------------------------------------
def test_record_unsupported_observation_writes_row(_temp_spec_csv):
    out = bp.record_unsupported_observation(
        "MMODX", category="Teleporter",
        installed_power_kw=12.5, observed_text="Teleporter 12.5 kW, no throughput.",
        rule_name="unknown-power-only",
    )
    assert out["written"] is True
    assert out["next_action"] == "Author a derivation rule for Teleporter (see observed power 12.5 kW)"
    rows = list(csv.DictReader(_temp_spec_csv.open()))
    best_effort = [r for r in rows
                   if r["machine_model_id"] == "MMODX" and r["extraction_method"].startswith("best-effort")]
    assert len(best_effort) == 1
    row = best_effort[0]
    assert row["extraction_method"] == "best-effort/no-rule"
    assert row["approval_status"] == "Needs Derivation Rule"
    assert row["confidence"] == "0.35"
    assert row["normalized_value"] == "12.5"
    assert row["unit"] == "kW"


def test_record_unsupported_observation_idempotent(_temp_spec_csv):
    """Re-queuing the same model does not duplicate the row — updates in place."""
    bp.record_unsupported_observation("MMODY", category="Wibble", installed_power_kw=8.0)
    bp.record_unsupported_observation("MMODY", category="Wibble", installed_power_kw=9.0, observed_text="refreshed")
    rows = list(csv.DictReader(_temp_spec_csv.open()))
    best_effort = [r for r in rows
                   if r["machine_model_id"] == "MMODY" and r["extraction_method"].startswith("best-effort")]
    assert len(best_effort) == 1
    assert best_effort[0]["normalized_value"] == "9"  # updated, not duplicated


def test_record_unsupported_observation_no_evidence_not_written(_temp_spec_csv):
    out = bp.record_unsupported_observation("MMODZ", category="Wobble", installed_power_kw=None)
    assert out["written"] is False
    assert "no parseable evidence" in out["reason"]
    rows = list(csv.DictReader(_temp_spec_csv.open()))
    assert not [r for r in rows if r["machine_model_id"] == "MMODZ"
                and r["extraction_method"].startswith("best-effort")]


def test_record_unsupported_observation_updates_existing_seed_in_place(_temp_spec_csv):
    """If the model already has a best-effort row, the latest observation supersedes it."""
    bp.record_unsupported_observation("MMOD001", category="Jet Dyeing Machine", installed_power_kw=42.0)
    rows = list(csv.DictReader(_temp_spec_csv.open()))
    best_effort = [r for r in rows
                   if r["machine_model_id"] == "MMOD001" and r["extraction_method"].startswith("best-effort")]
    assert len(best_effort) == 1
    assert best_effort[0]["normalized_value"] == "42"


# ---------------------------------------------------------------------------
# The derivation rules — unknown-category best-effort is lowest-conf, not None
# ---------------------------------------------------------------------------
def test_unknown_category_best_effort_is_low_conf_not_high_conf():
    """Carbon uses the best-effort value at LOWEST confidence (0.35), never a
    high-conf proxy, when the category has no rule."""
    from app.services.derivation_rules import derive_for_category

    class _Parse:
        power = staticmethod(bp._parse_power)
        throughput_kg_per_h = staticmethod(bp._parse_throughput_kg_per_h)

    r = derive_for_category("Teleporter", "Installed 10 kW, throughput 60 kg/h", _Parse)
    assert r is not None
    assert r.rule_name == "unknown-best-effort"
    assert r.confidence == 0.35
    # distinct from a proxy: this is a *derived* value, just flagged low-confidence.


def test_unknown_category_power_only_returns_no_kwh_but_surfaces_power():
    """Power-only + unknown category: no kWh derived (so no fake figure flows to
    carbon), but power IS observed so it gets queued for reviewer rule authoring."""
    text = "Teleporter 8 kW machine, no throughput."
    kwh, power, _throughput, basis = bd._derive_from_text(text, "Teleporter")
    assert kwh is None        # nothing fabricated
    assert power == 8.0       # the parseable evidence
    assert "needs rule" in basis or "unsupported" in basis


# ---------------------------------------------------------------------------
# discover_energy — queues the unsupported observation on a no-derivation live run
# ---------------------------------------------------------------------------
def _fake_master_with_model(machine_model_id, manufacturer, model, category, brochures=None):
    """Minimal master resolvable by discover_energy, no Tier-0 cache hit."""
    return {
        "machine_energy_by_model": {machine_model_id: {"approval_status": "Pending Validation", "electricity": ""}},
        "machine_brochures_by_model": {machine_model_id: brochures or []},
        "datasets": {
            "machine_models": [
                {"machine_model_id": machine_model_id, "manufacturer": manufacturer,
                 "model": model, "machine_category": category}
            ]
        },
    }


def test_discover_energy_queues_unsupported_observation(tmp_path, monkeypatch):
    """A live run on a no-rule category that parses power (but no throughput)
    records a best-effort observation. The spec-extractions write is redirected
    at a temp copy so the repo master is untouched (writer + reader both)."""
    spec_csv = _temp_spec_extractions_csv()
    _redirect_spec_extractions(monkeypatch, spec_csv)

    master = _fake_master_with_model("NOOP1", "Acme", "Z1", "Teleporter", brochures=[])
    queued = {}

    # Wrap the real writer so it runs against the temp CSV AND we capture its
    # return value (queued) to assert on the next_action. `bd` imported the name
    # at module load, so patching bd.record_unsupported_observation reaches the
    # call site inside discover_energy.
    _real_record = bp.record_unsupported_observation

    def _wrapped(mid, *, category, installed_power_kw, observed_text, rule_name):
        out = _real_record(mid, category=category, installed_power_kw=installed_power_kw,
                           observed_text=observed_text, rule_name=rule_name)
        queued.update(out)
        return out

    # Power-only brochure text (no throughput) on a no-rule category.
    brochure_text = b"Acme Teleporter Z1\nInstalled power: 14.0 kW\nno throughput here\n"

    with patch.object(bd, "load_master_data", return_value=master), \
         patch.object(bd, "record_unsupported_observation", side_effect=_wrapped), \
         patch("app.services.machine_source_finder._host_reachable", return_value=False), \
         patch.object(bd, "_ddg_candidates", return_value=(["https://acme.example/z1.pdf"], "")), \
         patch.object(bd, "_candidate_urls_from_bing", return_value=[]), \
         patch.object(bd.urllib.request, "urlopen",
                      side_effect=lambda *_a, **_k: _FakeResponse(brochure_text)):
        result = bd.discover_energy("NOOP1")

    # No derivation: KG-proxy retained, never a high-conf proxy, never crashes.
    assert result.derived_kwh_per_unit is None
    # An honest no-derivation attempt was recorded.
    assert result.attempts
    assert all(a.outcome != "derived" for a in result.attempts)
    # The best-effort observation WAS queued to the temp spec-extractions CSV.
    assert queued.get("written") is True
    assert "Teleporter" in queued["next_action"]
    assert queued["next_action"].startswith("Author a derivation rule for Teleporter")
    rows = list(csv.DictReader(spec_csv.open()))
    assert any(r["machine_model_id"] == "NOOP1" and r["extraction_method"].startswith("best-effort") for r in rows)


class _FakeResponse:
    def __init__(self, payload):
        self._payload = payload

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def read(self):
        return self._payload

    def headers(self):
        return {}


# ---------------------------------------------------------------------------
# brochure_review_summary — the unsupported backlog surfaces with next_action
# ---------------------------------------------------------------------------
def test_review_summary_surfaces_unsupported_next_action(tmp_path, monkeypatch):
    """A machine with a best-effort observation AND a no-rule category surfaces
    the actionable 'Author a derivation rule for {category}' next_action."""
    spec_csv = _temp_spec_extractions_csv()
    _redirect_spec_extractions(monkeypatch, spec_csv)

    # Queue an observation for an unknown-category machine in the real catalog.
    bp.record_unsupported_observation(
        "MMOD001", category="Jet Dyeing Machine", installed_power_kw=42.0,
        observed_text="observed 42 kW", rule_name="unknown-power-only",
    )
    # MMOD001's category (Jet Dyeing Machine) HAS a rule, so this row would prompt
    # promotion-review, not rule-authoring. To assert the rule-authoring path,
    # temporarily pretend the category has no rule via the summary's check.
    monkeypatch.setattr(
        "app.services.derivation_rules.has_category_rule", lambda c: False
    )

    summary_rows = bp.brochure_review_summary()
    mm = next(r for r in summary_rows if r["machine_model_id"] == "MMOD001")
    assert mm["rule_supported"] is False
    assert mm["unsupported_observation"] is not None
    assert mm["next_action"].startswith("Author a derivation rule for Jet Dyeing Machine")
    assert "42" in mm["next_action"]
