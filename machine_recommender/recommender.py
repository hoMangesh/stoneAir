"""Core recommendation engine.

Uses the inference engine to parse product names and determine
manufacturing workflows for any product, even undocumented ones.
"""

from __future__ import annotations

from typing import Optional

from .inference import InferenceEngine
from .models import InferredProduct, ManufacturingProcess, WorkflowResult


class ManufacturingRecommender:
    """Recommends manufacturing processes and machines for any product."""

    def __init__(self) -> None:
        self.engine = InferenceEngine()

    def recommend(self, product_name: str, include_optional: bool = True) -> Optional[WorkflowResult]:
        """Recommend manufacturing workflow for any product name.

        Uses attribute inference so even previously unseen products work.
        """
        product = self._parse(product_name)
        if product is None:
            return None

        return self._build_result(product, include_optional)

    def get_industry(self, product_name: str) -> str:
        """Determine the industry — currently always Clothing & Apparel."""
        return "Clothing & Apparel"

    def get_product_info(self, product_name: str) -> Optional[dict]:
        """Get inferred product info without full workflow."""
        product = self._parse(product_name)
        if product is None:
            return None
        material_name = ""
        if product.material_id:
            mat = self.engine._materials.get(product.material_id)
            if mat:
                material_name = mat.get("name", product.material_id)
        return {
            "name": product.raw_name,
            "category": product.category,
            "product_type": product.product_type_name,
            "material": material_name or product.material_id or "Unknown",
            "fabric_structure": product.fabric_structure_determined,
            "gender": product.gender or "Unisex",
            "features": product.detected_features,
        }

    def get_suggestions(self, partial: str) -> list[str]:
        """Suggest known products from the lexicon for a partial match."""
        partial = partial.strip().lower()
        suggestions: set[str] = set()

        for entry in self.engine._lexicon.get("product_type_keywords", []):
            for pattern in entry["words"]:
                if partial in pattern or pattern in partial:
                    type_info = self.engine._product_types.get(entry["type_id"])
                    if type_info:
                        suggestions.add(type_info["name"])
                    break

        return sorted(suggestions)

    def export_json(self, product_name: str, include_optional: bool = True) -> Optional[dict]:
        """Export recommendation as JSON-serializable dict."""
        result = self.recommend(product_name, include_optional)
        if result is None:
            return None
        return {
            "industry": result.industry,
            "product": result.product_name,
            "category": result.category,
            "product_type": result.product_type,
            "material": result.material,
            "fabric_structure": result.fabric_structure,
            "features": result.features,
            "workflow": [
                {
                    "process": p.name,
                    "description": p.description,
                    "optional": p.optional,
                    "machines": [
                        {
                            "name": m.name,
                            "category": m.category,
                            "purpose": m.purpose,
                            "automation": m.automation,
                        }
                        for m in p.machines
                    ],
                }
                for p in result.workflow
            ],
        }

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    def _parse(self, product_name: str) -> Optional[InferredProduct]:
        """Parse product name using inference engine."""
        return self.engine.parse_product(product_name)

    def _build_result(self, product: InferredProduct, include_optional: bool) -> WorkflowResult:
        """Build a WorkflowResult from an InferredProduct."""
        all_processes = self.engine.infer_workflow(product)

        if not include_optional:
            all_processes = [p for p in all_processes if not p.optional]

        material_name = ""
        if product.material_id:
            mat = self.engine._materials.get(product.material_id)
            if mat:
                material_name = mat.get("name", product.material_id)

        type_info = self.engine._product_types.get(product.product_type_id, {})
        typical = set(type_info.get("typical_features", []))
        effective_features = sorted(typical | set(product.detected_features))

        return WorkflowResult(
            industry="Clothing & Apparel",
            product_name=product.raw_name,
            category=product.category,
            product_type=product.product_type_name,
            material=material_name or product.material_id or "Generic",
            fabric_structure=product.fabric_structure_determined,
            features=effective_features,
            workflow=all_processes,
        )
