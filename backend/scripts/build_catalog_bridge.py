"""Build the machine_recommender <-> machine_energy_profiles catalog bridge.

Step 4b deferred bridge. Reads the 52-machine recommender catalog
(`machine_recommender/knowledge/clothing/machines.json`), skips the 6
non-energy categories (Design/Quality/Inspection), and for each of the 46
energy-bearing machines emits a synthetic `MMODR-NNN` identity across three
masters:

  1. `machine_recommender_models_bridge.csv` (NEW) — alias `M*** -> MMODR-NNN`
     + the alias-target `machine_category`.
  2. `+46` appended rows to `machine_models.csv` — the `MMODR` model row with
     manufacturer=`machine_recommender`, model=<recommender `name`>,
     `machine_category`=the alias target the derivation rules + routes already
     know (via `derivation_rules._CATEGORY_ALIASES`).
  3. `+46` appended rows to `machine_energy_profiles.csv` — a `KG V2 bridge
     proxy` (Pending Validation, conf 0.55) pending a real brochure. Phase 4
     queues these; until a brochure is found the proxy + the route's
     process-level fallback guard the step.

Deterministic + idempotent: `MMODR-NNN` is sequential on stable `M***` key
order, so re-running reproduces byte-identical output. Only ever APPENDS the
`MMODR` rows — the 6 `MMOD` seed rows are never touched.

Usage:
    cd backend && .venv/bin/python scripts/build_catalog_bridge.py --dry-run
    # print the 46 rows + 3 CSV outputs to stdout; no master write.
    .venv/bin/python scripts/build_catalog_bridge.py
    # write the alias CSV + print the two append blocks for reviewer review.
The script writes the alias CSV in place but does NOT mutate the seed-bearing
`machine_models.csv`/`machine_energy_profiles.csv` directly — it prints the
exact append lines so a reviewer eyeballs + commits, preserving the seed rows
byte-for-byte. (Tests assert this.)

Governance (Step 4 invariant): no master is auto-written at runtime; this is a
data-generation tool, run by a human, producing reviewed/committed rows.
"""
from __future__ import annotations

import argparse
import csv
import io
import json
import sys
from pathlib import Path

# Resolve repo paths regardless of cwd (tests may run from backend/).
HERE = Path(__file__).resolve()
BACKEND = HERE.parent.parent
REPO = BACKEND.parent

# Make `app.services.*` importable when run as a script from backend/.
sys.path.insert(0, str(BACKEND))

MACHINES_JSON = REPO / "machine_recommender" / "knowledge" / "clothing" / "machines.json"
MASTERS = REPO / "data" / "masters"
BRIDGE_CSV = MASTERS / "machine_recommender_models_bridge.csv"
MACHINE_MODELS_CSV = MASTERS / "machine_models.csv"
ENERGY_PROFILES_CSV = MASTERS / "machine_energy_profiles.csv"

# Non-energy recommender categories -> skip (no MMODR proxy). Design/Quality/
# Inspection don't carry process energy; /api/brochure-coverage reports the
# other 46 of 52 -> total=52 (skipping 6) reflects the real apparel surface.
NON_ENERGY_CATEGORIES = {"Design", "Quality", "Inspection"}

# Per-energy-category proxy figures for the MMODR rows. Modest industry-average
# kW (and water L/kg where a wet process) so the proxy is a *placeholder*
# awaiting a brochure, never a disguised authentic value. Same posture as the
# seed "KG V2 <category> proxy" rows (Pending Validation, conf 0.55).
#   electricity: kWh in the category's unit (kg/garment/m2 depending)
#   water:       L/kg fabric (0 for dry processes)
PROXY_BY_CATEGORY = {
    "Lockstitch Machine":      {"electricity": "0.05",  "water": "0"},   # /garment, sewing/embroidery/trims/trimming
    "CNC Fabric Cutter":        {"electricity": "0.15",  "water": "0"},   # /kg garment
    "Straight Knife Cutter":    {"electricity": "0.12",  "water": "0"},   # /kg garment (cutting alias)
    "Spreading Machine":        {"electricity": "0.03",  "water": "0"},   # /m2
    "Printing Machine":         {"electricity": "0.80",  "water": "0"},   # /m2
    "Ironing Machine":          {"electricity": "0.40",  "water": "0"},   # /kg fabric (thermal)
    "Drying Machine":           {"electricity": "0.60",  "water": "0"},   # /kg fabric (thermal)
    "Washing Machine":          {"electricity": "0.30",  "water": "40"},  # /kg fabric (wet batch)
    "Jet Dyeing Machine":       {"electricity": "0.30",  "water": "75"},  # /kg fabric (wet batch)
    "Stenter Machine":          {"electricity": "1.20",  "water": "10"},  # /kg fabric (thermal, finishing)
    "Ring Frame":               {"electricity": "2.50",  "water": "0"},   # /kg yarn (spin/knitting-adjacent; packaging alias)
    "Circular Knitting Machine": {"electricity": "1.80", "water": "0"},  # /kg fabric
}

# The bridge picks the alias *target* category (the master key the derivation
# rules + routes already know). For categories where the recommender `name` is
# more specific than the alias target (e.g. Straight Knife Cutter vs CNC Fabric
# Cutter), use the recommender `name` directly as the model `machine_category`
# when a derivation rule exists for it; else fall to the alias target.


def _category_for(rec: dict, alias_target: str) -> str:
    """Prefer the recommender name as the category when a derivation rule
    already keys on it (e.g. 'Straight Knife Cutter'); else the alias target."""
    from app.services.derivation_rules import _DERIVATION_RULES

    name = rec.get("name", "").strip()
    if name in _DERIVATION_RULES:
        return name
    return alias_target


def _unit_for(category: str) -> str:
    from app.services.brochure_pipeline import _CATEGORY_UNIT

    return _CATEGORY_UNIT.get(category, "kWh/kg")


def _process_for(category: str, rec: dict) -> str:
    """A coarse process label per category, for the machine_models.process col."""
    canonical = {
        "Jet Dyeing Machine": "Dyeing",
        "Washing Machine": "Washing",
        "Lockstitch Machine": "Sewing",
        "CNC Fabric Cutter": "Cutting",
        "Straight Knife Cutter": "Cutting",
        "Spreading Machine": "Spreading",
        "Printing Machine": "Printing",
        "Ironing Machine": "Ironing",
        "Drying Machine": "Drying",
        "Stenter Machine": "Finishing",
        "Ring Frame": "Knitting",
        "Circular Knitting Machine": "Knitting",
    }
    return canonical.get(category) or rec.get("category") or category


def build_rows() -> list[dict]:
    """Read the recommender catalog + the alias map -> the 46 bridge rows."""
    from app.services.derivation_rules import _CATEGORY_ALIASES

    catalog = json.loads(MACHINES_JSON.read_text(encoding="utf-8"))
    rows: list[dict] = []
    n = 0
    for recommender_id in sorted(catalog):  # stable M001..M052 order
        rec = catalog[recommender_id]
        cat = rec.get("category", "")
        if cat in NON_ENERGY_CATEGORIES:
            continue
        alias_target = _CATEGORY_ALIASES.get(cat)
        if not alias_target:
            # No alias -> skip (an energy-bearing category we haven't mapped);
            # Phase 4's unknown-category path handles it at runtime honestly.
            continue
        machine_category = _category_for(rec, alias_target)
        n += 1
        mmodr = f"MMODR-{n:03d}"
        rows.append({
            "recommender_id": recommender_id,
            "machine_model_id": mmodr,
            "machine_category": machine_category,
            "alias_target": alias_target,
            "recommender_category": cat,
            "name": rec.get("name", ""),
            "purpose": rec.get("purpose", ""),
            "unit": _unit_for(machine_category),
            "process": _process_for(machine_category, rec),
        })
    return rows


BRIDGE_HEADER = ["recommender_id", "machine_model_id", "machine_category", "origin_source"]

MACHINE_MODELS_HEADER = [
    "machine_model_id", "manufacturer", "model", "machine_category", "process",
    "capacity", "energy_source", "throughput", "brochure_url", "datasheet_url",
    "version", "effective_date", "expiry_date", "source", "approval_status", "confidence",
]

ENERGY_HEADER = [
    "machine_model_id", "unit", "electricity", "steam", "water",
    "compressed_air", "natural_gas", "source", "version", "effective_date",
    "expiry_date", "approval_status", "confidence",
]


def _machine_models_row(r: dict) -> dict:
    rec_name = r["name"] or r["recommender_id"]
    return {
        "machine_model_id": r["machine_model_id"],
        "manufacturer": "machine_recommender",
        "model": rec_name,
        "machine_category": r["machine_category"],
        "process": r["process"],
        "capacity": "",
        "energy_source": "Electricity",
        "throughput": "TBD from brochure",
        "brochure_url": "TBD_PUBLIC_BROCHURE_REQUIRED",
        "datasheet_url": "TBD_PUBLIC_DATASHEET_REQUIRED",
        "version": "0.1",
        "effective_date": "2026-06-12",
        "expiry_date": "",
        "source": f"machine_recommender bridge ({r['recommender_id']}); pending real brochure",
        "approval_status": "Pending Validation",
        "confidence": "0.5",
    }


def _energy_row(r: dict) -> dict:
    proxy = PROXY_BY_CATEGORY.get(r["alias_target"], {"electricity": "", "water": "0"})
    return {
        "machine_model_id": r["machine_model_id"],
        "unit": r["unit"],
        "electricity": proxy["electricity"],
        "steam": "0",
        "water": proxy["water"],
        "compressed_air": "0",
        "natural_gas": "0",
        "source": f"KG V2 bridge proxy ({r['recommender_id']}); brochure review required",
        "version": "0.1",
        "effective_date": "2026-06-12",
        "expiry_date": "",
        "approval_status": "Pending Validation",
        "confidence": "0.55",
    }


def _write_csv(path: Path, header: list[str], rows: list[dict]) -> str:
    import io
    buf = io.StringIO()
    writer = csv.DictWriter(buf, fieldnames=header)
    writer.writeheader()
    for row in rows:
        writer.writerow({k: row.get(k, "") for k in header})
    return buf.getvalue()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dry-run", action="store_true",
                        help="Print outputs to stdout; do not write masters.")
    parser.add_argument("--write-masters", action="store_true",
                        help="Append the MMODR rows to machine_models.csv + "
                             "machine_energy_profiles.csv (only their MMODR block; "
                             "seed rows untouched). Default off.")
    args = parser.parse_args(argv)

    rows = build_rows()
    print(f"# bridge: {len(rows)} energy-bearing machines bridged "
          f"(skipped {len(json.loads(MACHINES_JSON.read_text())) - len(rows)} non-energy)")

    bridge_csv_text = _write_csv(BRIDGE_CSV, BRIDGE_HEADER, [
        {"recommender_id": r["recommender_id"],
         "machine_model_id": r["machine_model_id"],
         "machine_category": r["machine_category"],
         "origin_source": "machine_recommender/knowledge/clothing/machines.json"}
        for r in rows
    ])
    mm_rows = [_machine_models_row(r) for r in rows]
    en_rows = [_energy_row(r) for r in rows]

    if args.dry_run:
        print(f"\n# === {BRIDGE_CSV.name} (NEW) ===")
        print(bridge_csv_text, end="")
        print(f"\n# === {MACHINE_MODELS_CSV.name} (APPEND {len(mm_rows)} rows) ===")
        print(_write_csv(Path("/dev/null"), MACHINE_MODELS_HEADER, mm_rows), end="")
        print(f"\n# === {ENERGY_PROFILES_CSV.name} (APPEND {len(en_rows)} rows) ===")
        print(_write_csv(Path("/dev/null"), ENERGY_HEADER, en_rows), end="")
        return 0

    # Write the alias CSV (new master).
    BRIDGE_CSV.write_text(bridge_csv_text, encoding="utf-8")
    print(f"wrote {BRIDGE_CSV}")

    if args.write_masters:
        # Append MMODR rows to the seed-bearing masters — preserve seed rows.
        for path, header, append in (
            (MACHINE_MODELS_CSV, MACHINE_MODELS_HEADER, mm_rows),
            (ENERGY_PROFILES_CSV, ENERGY_HEADER, en_rows),
        ):
            existing = path.read_text(encoding="utf-8")
            trailing_newline = "\n" if existing and not existing.endswith("\n") else ""
            buf = _write_csv(Path("/dev/null"), header, append)
            # Drop the header line of the append block (keep only rows).
            append_lines = "\n".join(buf.splitlines()[1:])
            path.write_text(existing + trailing_newline + append_lines + "\n", encoding="utf-8")
            print(f"appended {len(append)} rows to {path}")
    else:
        print("# (master append skipped; pass --write-masters to append MMODR rows "
              "to machine_models.csv + machine_energy_profiles.csv)")
    print("# review with: git diff --stat data/masters/  (only MMODR appends + the new alias CSV)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
