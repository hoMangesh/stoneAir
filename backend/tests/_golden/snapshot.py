"""Golden-output snapshot for the apparel pipeline — the Core Stabilization
parity baseline. Run once BEFORE extraction to capture today's behavior; run
again after Steps 3/4/6 and diff the JSON (sorted keys) to prove apparel output
is byte-identical. The(deferred to WS2) `digital twin` does not exist yet, so
this drives the pipeline the way main.py::analyze_product does today.

Usage: .venv/bin/python tests/_golden/snapshot.py  (writes snapshot.json)
       .venv/bin/python tests/_golden/snapshot.py --check  (diff vs snapshot.json)
"""
from __future__ import annotations

import json
import sys
from collections import defaultdict
from pathlib import Path

from app.services.document_intelligence import extract_document_signals
from app.services.product_intelligence import classify_product, match_template
from app.services.manufacturing_reconstruction import reconstruct_route
from app.services.reporting import build_report
from app.services.resource_models import estimate_resources
from app.services.route_resolution import resolve_route

HERE = Path(__file__).resolve().parent
SNAPSHOT_PATH = HERE / "snapshot.json"

# Representative fixtures spanning knit/woven + cotton/synthetic + blend.
FIXTURES = [
    {
        "name": "cotton_tee_single",
        "description": "cotton tee",
        "bom": [{"material": "cotton", "percent": 100, "weight_g": 215, "origin": "India"}],
        "origin": "India",
    },
    {
        "name": "poly_tee_blend",
        "description": "polyester performance tee",
        "bom": [
            {"material": "polyester", "percent": 92, "weight_g": 170, "origin": "China"},
            {"material": "elastane", "percent": 8, "origin": "China"},
        ],
        "origin": "China",
    },
    {
        "name": "denim_jeans",
        "description": "five pocket denim jeans",
        "bom": [
            {"material": "cotton", "percent": 98, "weight_g": 700, "origin": "India"},
            {"material": "elastane", "percent": 2, "origin": "India"},
        ],
        "origin": "India",
    },
]


def _activity_totals(rows: list[dict]) -> dict[str, float]:
    agg: dict[tuple[str, str], float] = defaultdict(float)
    for r in rows:
        agg[(r["activity_type"], r["activity_unit"])] += r["carbon_kgco2e"]
    return {f"{k[0]}|{k[1]}": round(v, 5) for k, v in sorted(agg.items())}


def _run_fixture(fx: dict) -> dict:
    sig = extract_document_signals(
        fx["description"], [], bom_components=fx["bom"], declared_origin=fx["origin"]
    )
    cls = classify_product(sig)
    tm = match_template(str(cls["taxonomy"]["taxonomy_id"]), sig)
    cr = resolve_route(
        str(cls["taxonomy"]["taxonomy_id"]),
        sig,
        default_route_id=str(tm["template"]["default_route_id"]),
    )
    route = reconstruct_route(cr["route_id"])
    res = estimate_resources(route["steps"], int(tm["resolved_weight_g"]), origin_context={})
    rpt = build_report(cls, tm, route, res)
    return {
        "taxonomy_id": cls["taxonomy"]["taxonomy_id"],
        "template_id": tm["template"]["template_id"],
        "route_id": route["route_id"],
        "resolved_weight_g": tm["resolved_weight_g"],
        "totals": res["totals"],
        "activity_count": len(res["activity_trace"]),
        "activity_totals": _activity_totals(res["activity_trace"]),
        "process_breakdown": res["process_breakdown"],
        "machine_breakdown": res["machine_breakdown"],
        "impact": rpt["impact"],
    }


def build_snapshot() -> dict:
    return {fx["name"]: _run_fixture(fx) for fx in FIXTURES}


def main() -> int:
    check = "--check" in sys.argv
    snapshot = build_snapshot()
    if check:
        if not SNAPSHOT_PATH.exists():
            print("NO SNAPSHOT — run without --check first", file=sys.stderr)
            return 2
        expected = json.loads(SNAPSHOT_PATH.read_text())
        if json.dumps(snapshot, sort_keys=True) == json.dumps(expected, sort_keys=True):
            print("PARITY OK — apparel output byte-identical to baseline")
            return 0
        # Diff in a readable form
        for name in snapshot:
            if name not in expected:
                print(f"  + {name}: new fixture")
                continue
            for key in snapshot[name]:
                if snapshot[name][key] != expected[name].get(key):
                    print(f"  ! {name}.{key}:\n      was: {expected[name].get(key)}\n      now: {snapshot[name][key]}")
        print("PARITY DRIFT — apparel output changed (see above)", file=sys.stderr)
        return 1
    SNAPSHOT_PATH.write_text(json.dumps(snapshot, indent=2, sort_keys=True) + "\n")
    print(f"WROTE {SNAPSHOT_PATH} ({len(snapshot)} fixtures)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
