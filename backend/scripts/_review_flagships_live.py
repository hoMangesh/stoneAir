"""One-off live-discovery REVIEW harness for the 4 flagship machines.

Runs discover_energy for MMOD001..MMOD004 (Thies iMaster H2O, Mayer & Cie
Relanit, Rieter G 38, Juki DDL-8700) and prints each derived candidate +
source URL for human review. NO promotion, NO energy-master write at all.

Side-effect containment: discover_energy auto-persists a live derivation via
persist_brochure_observations (machine_brochures.csv) and may record an
unsupported observation (machine_spec_extractions.csv). To respect the
"review before any repo-master write" govern, BOTH append/update writers are
redirected at TEMP COPIES for this run, mirroring the Phase 4 test fixture.
The cached loader is pointed at temp copies too so persist_brochure_observations
(in-place update by id) sees a copy, not the repo master. Real repo masters are
touched only by reads (safe).

Run: cd backend && .venv/bin/python scripts/_review_flagships_live.py
"""
from __future__ import annotations

import csv
import shutil
import sys
import tempfile
from pathlib import Path

# scripts/ is not on the package path; add backend/ so `app` imports work.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from unittest.mock import patch

from app import config
from app.services import brochure_discovery as bd
from app.services import brochure_pipeline as bp
from app.services import knowledge_loader

MASTER_ROOT = Path(config.MASTER_DATASETS["machine_energy_profiles"]).parent

FLAGSHIPS = [
    ("MMOD001", "Thies", "iMaster H2O", "Jet Dyeing Machine", "kWh/kg fabric", "0.15 (demo seed, NOT authentic)"),
    ("MMOD002", "Mayer & Cie", "Relanit", "Circular Knitting Machine", "kWh/kg fabric", "1.8 (KG V2 proxy)"),
    ("MMOD003", "Rieter", "G 38", "Ring Frame", "kWh/kg yarn", "2.5 (KG V2 proxy)"),
    ("MMOD004", "Juki", "DDL-8700", "Lockstitch Machine", "kWh/garment", "0.05 (KG V2 proxy)"),
]


def _redirect_writers():
    tmp_dir = Path(tempfile.mkdtemp(prefix="flagship_review_"))
    copies = {}
    for key, src in (
        ("machine_brochures", MASTER_ROOT / "machine_brochures.csv"),
        ("machine_spec_extractions", MASTER_ROOT / "machine_spec_extractions.csv"),
    ):
        dst = tmp_dir / src.name
        shutil.copy(src, dst)
        copies[key] = dst
    # Patch the two writer constants in brochure_pipeline.
    patches = [
        patch.object(bp, "_MACHINE_BROCHURES_CSV", copies["machine_brochures"]),
        patch.object(bp, "_SPEC_EXTRACTIONS_CSV", copies["machine_spec_extractions"]),
    ]
    for p in patches:
        p.start()
    # Point the loader's MASTER_DATASETS at the temp copies too so the
    # in-place update reads the copy, not the repo master.
    redirected = dict(config.MASTER_DATASETS)
    redirected["machine_brochures"] = copies["machine_brochures"]
    redirected["machine_spec_extractions"] = copies["machine_spec_extractions"]
    config.MASTER_DATASETS = redirected          # redirect the config binding
    knowledge_loader.MASTER_DATASETS = redirected # redirect the loader's own binding
    knowledge_loader.load_master_data.cache_clear()
    return tmp_dir, copies


def _restore(orig_master_datasets):
    patch.stopall()
    config.MASTER_DATASETS = orig_master_datasets
    knowledge_loader.MASTER_DATASETS = orig_master_datasets
    knowledge_loader.load_master_data.cache_clear()


def main() -> int:
    orig_master_datasets = dict(config.MASTER_DATASETS)
    tmp_dir, _copies = _redirect_writers()
    try:
        for mid, mfr, model, cat, unit, current in FLAGSHIPS:
            print(f"\n{'=' * 78}")
            print(f"{mid}  {mfr} {model}  [{cat}]")
            print(f"current proxy: {current}")
            print("-" * 78)
            res = bd.discover_energy(mid)
            if res.cache_hit:
                print(f"CACHE HIT (already promoted): {res.derived_kwh_per_unit} {res.unit}")
                print(f"  basis: {res.basis}")
                continue
            if res.derived_kwh_per_unit is not None:
                print(f"DERIVED: {res.derived_kwh_per_unit:g} {res.unit}")
                print(f"  installed power : {res.installed_power_kw} kW")
                print(f"  throughput      : {res.throughput_kg_per_h} kg/h")
                print(f"  basis           : {res.basis}")
            else:
                print("NO DERIVATION (KG proxy retained)")
                print(f"  basis: {res.basis}")
            if res.attempts:
                print(f"  attempts ({len(res.attempts)}):")
                for a in res.attempts:
                    url = a.url or ""
                    note = f" kwh={a.derived_kwh_per_unit}" if a.derived_kwh_per_unit is not None else ""
                    powr = f" power={a.installed_power_kw}" if a.installed_power_kw is not None else ""
                    thru = f" thru={a.throughput_kg_per_h}" if a.throughput_kg_per_h is not None else ""
                    print(f"    [{a.outcome}] {a.strategy}{note}{powr}{thru}")
                    if url:
                        print(f"        url: {url}")
    finally:
        _restore(orig_master_datasets)
        shutil.rmtree(tmp_dir, ignore_errors=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
