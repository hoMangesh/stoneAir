"""Bridge between the machine_recommender package and the LCA inference pipeline.

The recommender knows the *downstream* cut-and-sew machine workflow for any
product name (52 machines, fuzzy name parsing, context-aware selection) but
nothing about farming->fiber upstream or emissions. The backend knows the
full farming->packaging route and carbon but only for the 8 static routes.

This bridge lets the analyze pipeline answer "what machines does THIS specific
product need?" even when the classified product has no KG-backed route, by
asking the recommender for a per-name workflow. The result is exposed as an
enrichment layer and as a dedicated /api/workflow endpoint.
"""
from __future__ import annotations

import sys
from functools import lru_cache
from pathlib import Path
from typing import Any

from app.services.knowledge_loader import confidence_level

# The machine_recommender package lives at the repo root, which is not on the
# backend's sys.path by default. Insert it so the backend can import the package
# without requiring callers to set PYTHONPATH.
_REPO_ROOT = str(Path(__file__).resolve().parents[3])
if _REPO_ROOT not in sys.path:
    sys.path.insert(0, _REPO_ROOT)


@lru_cache(maxsize=1)
def _get_recommender():
    # Import lazily so the backend still boots if the package is unavailable.
    from machine_recommender import ManufacturingRecommender

    return ManufacturingRecommender()


def recommend_workflow(product_name: str, include_optional: bool = False) -> dict[str, Any] | None:
    """Return a serializable machine workflow for any product name.

    Returns None when the name cannot be resolved to a product type (the
    recommender's fuzzy fallback still resolves most names at ratio >= 0.6).
    """
    recommender = _get_recommender()
    try:
        result = recommender.recommend(product_name, include_optional=include_optional)
    except Exception:
        return None
    if result is None:
        return None

    workflow = []
    for process in result.workflow:
        workflow.append(
            {
                "process": process.name,
                "description": process.description,
                "optional": process.optional,
                "machines": [
                    {
                        "name": machine.name,
                        "category": machine.category,
                        "purpose": machine.purpose,
                        "automation": machine.automation,
                    }
                    for machine in process.machines
                ],
            }
        )

    # Sparse by design: a workflow of N processes with M machines each is only as
    # trustworthy as the weakest link, so confidence follows the process coverage.
    product_info = recommender.get_product_info(product_name) or {}
    machine_count = sum(len(step["machines"]) for step in workflow)
    coverage_score = 0.7 if machine_count else 0.35

    return {
        "resolved": {
            "product_name": result.product_name,
            "category": result.category,
            "product_type": result.product_type,
            "material": result.material,
            "fabric_structure": result.fabric_structure,
            "features": list(result.features),
        },
        "workflow": workflow,
        "confidence": confidence_level(coverage_score),
        "machine_count": machine_count,
        "process_count": len(workflow),
        "source": "machine_recommender (dynamic per-name inference)",
    }


def infer_workflow_record(product_name: str) -> dict[str, Any] | None:
    """Build an inference-engine trace record for the dynamic workflow step."""
    workflow = recommend_workflow(product_name)
    if workflow is None:
        return None
    return {
        "inference_id": "INF-RUN-DYNAMIC-WORKFLOW",
        "inference_type": "Dynamic Machine Workflow",
        "input_data": product_name,
        "output_data": f"{workflow['process_count']} processes, {workflow['machine_count']} machines ({workflow['resolved']['material']})",
        "agent": "Machine Workflow Agent",
        "confidence": workflow["confidence"],
        "source": workflow["source"],
        "evidence": [
            f"product_type={workflow['resolved']['product_type']}",
            f"fabric_structure={workflow['resolved']['fabric_structure']}",
            f"features={','.join(workflow['resolved']['features']) or 'none'}",
        ],
    }
