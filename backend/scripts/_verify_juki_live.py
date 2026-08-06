"""Live end-to-end: discover_energy('MMOD004') against the REAL committed master
(machine_brochures.csv now has the Juki URL on MBR004).

Containment: writes (persist_brochure_observations / record_unsupported_observation)
redirect to TEMP COPIES so the live DB-persist of the derivation lands on a copy,
not the repo master. Reads hit the real master (safe).

Run: cd backend && .venv/bin/python scripts/_verify_juki_live.py
"""
from __future__ import annotations

import shutil
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from unittest.mock import patch

from app import config
from app.services import brochure_discovery as bd
from app.services import brochure_pipeline as bp
from app.services import knowledge_loader

MASTER_ROOT = Path(config.MASTER_DATASETS["machine_energy_profiles"]).parent
orig_master = dict(config.MASTER_DATASETS)


def main() -> int:
    tmp = Path(tempfile.mkdtemp(prefix="juki_live_"))
    try:
        spec_dst = tmp / "machine_spec_extractions.csv"
        broc_dst = tmp / "machine_brochures.csv"
        shutil.copy(MASTER_ROOT / "machine_spec_extractions.csv", spec_dst)
        shutil.copy(MASTER_ROOT / "machine_brochures.csv", broc_dst)
        with patch.object(bp, "_MACHINE_BROCHURES_CSV", broc_dst), \
             patch.object(bp, "_SPEC_EXTRACTIONS_CSV", spec_dst):
            red = dict(orig_master)
            red["machine_brochures"] = broc_dst
            red["machine_spec_extractions"] = spec_dst
            config.MASTER_DATASETS = red
            knowledge_loader.MASTER_DATASETS = red
            knowledge_loader.load_master_data.cache_clear()
            try:
                res = bd.discover_energy("MMOD004")
            finally:
                patch.stopall()
                config.MASTER_DATASETS = orig_master
                knowledge_loader.MASTER_DATASETS = orig_master
                knowledge_loader.load_master_data.cache_clear()
        print("discover_energy('MMOD004') LIVE ->")
        print(f"  derived_kwh_per_unit = {res.derived_kwh_per_unit}")
        print(f"  unit                  = {res.unit}")
        print(f"  installed_power_kw    = {res.installed_power_kw}")
        print(f"  basis                 = {res.basis}")
        print(f"  attempts:")
        for a in res.attempts:
            print(f"    [{a.outcome}] {a.strategy}  url={a.url}")
        ok = res.derived_kwh_per_unit is not None
        print("\nOK" if ok else "\nNO DERIVATION")
        return 0 if ok else 1
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    raise SystemExit(main())
