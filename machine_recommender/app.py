#!/usr/bin/env python3
"""CLI for the Manufacturing Inference Engine.

Usage:
    python app.py
    python app.py "Neoprene Wetsuit"
    python app.py "Silk Evening Gown" --json
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

# Allow running two ways:
#   1. `python app.py` from inside machine_recommender/  -> bare import
#   2. `python -m machine_recommender.app` from repo root -> package import
# Adding the parent dir to sys.path keeps the original bare import working
# without forcing callers to change how they launch the CLI.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

try:
    from recommender import ManufacturingRecommender
except ImportError:
    from machine_recommender.recommender import ManufacturingRecommender


def display_table(result) -> None:
    """Print formatted workflow table."""
    sep = "=" * 72
    print()
    print(sep)
    print(f"  INDUSTRY:          {result.industry}")
    print(f"  PRODUCT:           {result.product_name}")
    print(f"  CATEGORY:          {result.category}")
    print(f"  PRODUCT TYPE:      {result.product_type}")
    print(f"  MATERIAL:          {result.material}")
    print(f"  FABRIC STRUCTURE:  {result.fabric_structure}")
    if result.features:
        print(f"  DETECTED FEATURES: {', '.join(result.features)}")
    print(sep)
    print()

    for i, process in enumerate(result.workflow, 1):
        tag = " (Optional)" if process.optional else ""
        print(f"  {i}. {process.name}{tag}")
        print(f"     {process.description}")
        for j, machine in enumerate(process.machines, 1):
            prefix = "└" if j == len(process.machines) else "├"
            auto = f" [{machine.automation}]" if machine.automation else ""
            print(f"     {prefix}── {machine.name}{auto}")
        if not process.machines:
            print("     └── (No machines specified)")
        print()

    print(sep)


def run_interactive(recommender: ManufacturingRecommender) -> None:
    """Interactive mode."""
    print("\n  Manufacturing Inference Engine")
    print("  Type 'exit' to quit.")
    print()

    while True:
        try:
            user_input = input("  Enter Product Name: ").strip()
        except (EOFError, KeyboardInterrupt):
            print()
            break

        if not user_input:
            continue
        if user_input.lower() in ("exit", "quit"):
            break
        if user_input.lower() == "list":
            _list_known_types(recommender)
            continue

        result = recommender.recommend(user_input)

        if result is None:
            print(f"\n  [ERROR] Could not identify product type from '{user_input}'.")
            suggestions = recommender.get_suggestions(user_input)
            if suggestions:
                print(f"  Did you mean: {', '.join(suggestions)}?")
            else:
                print("  Try entering a more descriptive product name.")
            print()
            continue

        display_table(result)

        json_data = recommender.export_json(user_input)
        if json_data:
            print("\n  JSON Output:\n")
            print(json.dumps(json_data, indent=2))
            print()


def _list_known_types(recommender: ManufacturingRecommender) -> None:
    """List all known product types."""
    types = sorted(
        recommender.engine._product_types.keys(),
        key=lambda t: recommender.engine._product_types[t]["name"],
    )
    print("\n  Known Product Types:")
    print("  " + "-" * 50)
    for tid in types:
        info = recommender.engine._product_types[tid]
        print(f"  • {info['name']} ({info['category']})")
    print()


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Manufacturing Inference Engine — infer processes and machines for any product."
    )
    parser.add_argument("product", nargs="?", help="Product name")
    parser.add_argument("--json", action="store_true", help="JSON output only")
    parser.add_argument("--no-optional", action="store_true", help="Skip optional processes")
    parser.add_argument("--list", action="store_true", help="List known product types")
    args = parser.parse_args()

    recommender = ManufacturingRecommender()

    if args.list:
        _list_known_types(recommender)
        return

    if args.product:
        include_optional = not args.no_optional
        result = recommender.recommend(args.product, include_optional=include_optional)

        if result is None:
            print(f"\n  [ERROR] Could not identify product type from '{args.product}'.")
            suggestions = recommender.get_suggestions(args.product)
            if suggestions:
                print(f"  Did you mean: {', '.join(suggestions)}?")
            sys.exit(1)

        if args.json:
            json_data = recommender.export_json(args.product, include_optional=include_optional)
            print(json.dumps(json_data, indent=2))
        else:
            display_table(result)
            json_data = recommender.export_json(args.product, include_optional=include_optional)
            print("\n  JSON Output:\n")
            print(json.dumps(json_data, indent=2))
        return

    run_interactive(recommender)


if __name__ == "__main__":
    main()
