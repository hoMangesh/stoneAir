#!/usr/bin/env python3
"""Find likely machine models for a process at a geographic location.

The script uses the repository's master data:
  - data/masters/processes.csv
  - data/masters/machine_models.csv
  - data/masters/factories.csv
  - data/masters/factory_machine_map.csv

It is intentionally explainable. In apparel and footwear manufacturing,
the exact installed machine model is usually factory-specific. When the
location maps to a known factory, the script prioritizes models installed
there. Otherwise it falls back to process-compatible global models.

Examples:
  python machine_recommender/process_machine_lookup.py
  python machine_recommender/process_machine_lookup.py "Sewing" "Dhaka, Bangladesh"
  python machine_recommender/process_machine_lookup.py "Reactive dyeing" "Vietnam" --json
"""

from __future__ import annotations

import argparse
import csv
import json
from dataclasses import asdict, dataclass
from difflib import SequenceMatcher
from pathlib import Path
from typing import Iterable


REPO_ROOT = Path(__file__).resolve().parent.parent
MASTER_DIR = REPO_ROOT / "data" / "masters"


@dataclass(frozen=True)
class MachineCandidate:
    rank: int
    machine_model_id: str
    manufacturer: str
    model: str
    machine_category: str
    process: str
    location_match: str
    factory_name: str
    quantity: int
    confidence: float
    score: float
    reason: str
    source: str
    approval_status: str


def load_csv(name: str) -> list[dict[str, str]]:
    path = MASTER_DIR / name
    with path.open(newline="", encoding="utf-8-sig") as file:
        return list(csv.DictReader(file))


def normalize(value: str) -> str:
    return " ".join(
        value.lower()
        .replace("-", " ")
        .replace("_", " ")
        .replace(",", " ")
        .replace("/", " ")
        .split()
    )


def text_similarity(left: str, right: str) -> float:
    left_norm = normalize(left)
    right_norm = normalize(right)
    if not left_norm or not right_norm:
        return 0.0
    if left_norm == right_norm:
        return 1.0
    if left_norm in right_norm or right_norm in left_norm:
        return 0.9
    return SequenceMatcher(None, left_norm, right_norm).ratio()


def as_float(value: str, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def as_int(value: str, default: int = 0) -> int:
    try:
        return int(float(value))
    except (TypeError, ValueError):
        return default


def process_aliases(process: str, processes: Iterable[dict[str, str]]) -> list[str]:
    aliases = {process}
    process_norm = normalize(process)
    for row in processes:
        process_name = row.get("process_name", "")
        process_id = row.get("process_id", "")
        if text_similarity(process, process_name) >= 0.72 or process_norm == normalize(process_id):
            aliases.add(process_name)
            aliases.add(process_id)
    return sorted(alias for alias in aliases if alias)


def location_score(location: str, factory: dict[str, str] | None) -> tuple[float, str]:
    if not factory:
        return 0.15, "no factory-specific location match"

    location_norm = normalize(location)
    country = factory.get("country", "")
    region = factory.get("region", "")
    factory_name = factory.get("factory_name", "")

    country_norm = normalize(country)
    region_norm = normalize(region)
    factory_norm = normalize(factory_name)

    if factory_norm and factory_norm in location_norm:
        return 1.0, f"factory match: {factory_name}"
    if region_norm and region_norm in location_norm and country_norm and country_norm in location_norm:
        return 0.95, f"region and country match: {region}, {country}"
    if region_norm and region_norm in location_norm:
        return 0.85, f"region match: {region}"
    if country_norm and country_norm in location_norm:
        return 0.7, f"country match: {country}"
    if location_norm:
        fuzzy = max(
            text_similarity(location, country),
            text_similarity(location, region),
            text_similarity(location, factory_name),
        )
        if fuzzy >= 0.72:
            return 0.55, f"fuzzy location match: {factory_name or region or country}"
    return 0.0, "different or unknown location"


def find_machine_models(process: str, location: str, limit: int = 5) -> list[MachineCandidate]:
    processes = load_csv("processes.csv")
    machine_models = load_csv("machine_models.csv")
    factories = {row["factory_id"]: row for row in load_csv("factories.csv")}
    factory_map = load_csv("factory_machine_map.csv")

    model_by_id = {row["machine_model_id"]: row for row in machine_models}
    installations_by_model: dict[str, list[dict[str, str]]] = {}
    for row in factory_map:
        installations_by_model.setdefault(row["machine_model_id"], []).append(row)

    aliases = process_aliases(process, processes)
    candidates: list[MachineCandidate] = []

    for model in machine_models:
        process_match = max(text_similarity(alias, model.get("process", "")) for alias in aliases)
        category_match = max(text_similarity(alias, model.get("machine_category", "")) for alias in aliases)
        # Prefer the model's process label. Machine category is useful when
        # the user enters "lockstitch" or "jet dyeing machine", but weak fuzzy
        # category matches create noisy recommendations.
        category_compatibility = category_match if category_match >= 0.8 else 0.0
        compatibility = max(process_match, category_compatibility)
        if compatibility < 0.72:
            continue

        installations = installations_by_model.get(model["machine_model_id"], [])
        location_options: list[tuple[float, str, dict[str, str] | None, dict[str, str] | None]] = []
        for installed in installations:
            factory = factories.get(installed.get("factory_id", ""))
            loc_score, loc_reason = location_score(location, factory)
            location_options.append((loc_score, loc_reason, factory, installed))

        if location_options:
            best_location_score, loc_reason, factory, installed = max(
                location_options, key=lambda item: item[0]
            )
        else:
            best_location_score, loc_reason, factory, installed = location_score(location, None) + (None, None)

        source_confidence = as_float(model.get("confidence", ""), 0.0)
        installation_confidence = as_float((installed or {}).get("confidence", ""), 0.0)
        data_confidence = max(source_confidence, installation_confidence)
        quantity = as_int((installed or {}).get("quantity", ""), 0)
        quantity_boost = min(quantity, 100) / 1000

        score = (
            compatibility * 0.58
            + best_location_score * 0.25
            + data_confidence * 0.12
            + quantity_boost * 0.05
        )

        reason_parts = [
            f"process compatibility {compatibility:.2f}",
            loc_reason,
        ]
        if quantity:
            reason_parts.append(f"{quantity} installed machine(s) in mapped factory")
        if model.get("approval_status"):
            reason_parts.append(model["approval_status"])

        candidates.append(
            MachineCandidate(
                rank=0,
                machine_model_id=model["machine_model_id"],
                manufacturer=model.get("manufacturer", "Unknown"),
                model=model.get("model", "Unknown"),
                machine_category=model.get("machine_category", "Unknown"),
                process=model.get("process", "Unknown"),
                location_match=loc_reason,
                factory_name=(factory or {}).get("factory_name", ""),
                quantity=quantity,
                confidence=round(data_confidence, 2),
                score=round(score, 3),
                reason="; ".join(reason_parts),
                source=model.get("source", ""),
                approval_status=model.get("approval_status", ""),
            )
        )

    candidates.sort(key=lambda item: item.score, reverse=True)
    return [
        MachineCandidate(**{**asdict(candidate), "rank": index})
        for index, candidate in enumerate(candidates[:limit], start=1)
    ]


def print_table(candidates: list[MachineCandidate], process: str, location: str) -> None:
    print()
    print("=" * 88)
    print(f"Process:  {process}")
    print(f"Location: {location}")
    print("=" * 88)

    if not candidates:
        print("No candidate machine model found in the current knowledge base.")
        print("Try a broader process name such as Sewing, Knitting, Cutting, Reactive Dyeing, or Finishing.")
        return

    for candidate in candidates:
        print(f"{candidate.rank}. {candidate.manufacturer} {candidate.model}")
        print(f"   Machine category : {candidate.machine_category}")
        print(f"   Matched process  : {candidate.process}")
        print(f"   Score/confidence : {candidate.score:.3f} / {candidate.confidence:.2f}")
        if candidate.factory_name:
            print(f"   Factory evidence : {candidate.factory_name} ({candidate.quantity} installed)")
        print(f"   Why              : {candidate.reason}")
        print(f"   Source           : {candidate.source}")
        print()


def run_interactive() -> None:
    print("\nMachine Model Finder")
    print("Type 'exit' to quit.\n")
    while True:
        process = input("Enter industrial process: ").strip()
        if normalize(process) in {"exit", "quit"}:
            break
        if not process:
            continue

        location = input("Enter location: ").strip()
        if normalize(location) in {"exit", "quit"}:
            break
        if not location:
            location = "Unknown"

        candidates = find_machine_models(process, location)
        print_table(candidates, process, location)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Find likely machine models for an industrial process and location."
    )
    parser.add_argument("process", nargs="?", help="Industrial process, e.g. Sewing")
    parser.add_argument("location", nargs="?", help="Geographic location, e.g. Dhaka, Bangladesh")
    parser.add_argument("--limit", type=int, default=5, help="Number of ranked candidates to return")
    parser.add_argument("--json", action="store_true", help="Return JSON output")
    args = parser.parse_args()

    if not args.process:
        run_interactive()
        return

    location = args.location or "Unknown"
    candidates = find_machine_models(args.process, location, limit=args.limit)

    if args.json:
        print(json.dumps([asdict(candidate) for candidate in candidates], indent=2))
    else:
        print_table(candidates, args.process, location)


if __name__ == "__main__":
    main()
