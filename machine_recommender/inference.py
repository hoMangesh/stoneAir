"""Inference engine for manufacturing process recommendation.

Parses any product name to extract attributes (material, type, features),
then applies knowledge-based rules to determine the manufacturing workflow.
"""

from __future__ import annotations

import json
from difflib import SequenceMatcher
from pathlib import Path
from typing import Any, Optional

from .models import InferredProduct, Machine, ManufacturingProcess

_KNOWLEDGE_DIR = Path(__file__).parent / "knowledge"


class InferenceEngine:
    """Determines manufacturing processes by inferring product attributes."""

    def __init__(self, knowledge_dir: Optional[Path] = None) -> None:
        self._dir = knowledge_dir or _KNOWLEDGE_DIR
        self._lexicon: dict = {}
        self._materials: dict[str, dict] = {}
        self._product_types: dict[str, dict] = {}
        self._features_db: dict[str, dict] = {}
        self._processes_db: dict[str, dict] = {}
        self._machines_db: dict[str, dict] = {}
        self.load_knowledge()

    # ------------------------------------------------------------------
    # Load knowledge base
    # ------------------------------------------------------------------

    def load_knowledge(self) -> None:
        """Load all JSON knowledge files for every available industry."""
        industries = self._load_json("industries.json")
        for industry_id, info in industries.items():
            ind_dir = self._dir / info["directory"]
            self._load_industry_knowledge(ind_dir)

    def _load_industry_knowledge(self, path: Path) -> None:
        files = ["machines.json", "processes.json", "lexicon.json",
                 "materials.json", "product_types.json", "features.json"]
        for fname in files:
            fpath = path / fname
            if fpath.exists():
                data = self._load_json(str(fpath.relative_to(self._dir)))
                key = fname.replace(".json", "")
                if key == "machines":
                    self._machines_db = data
                elif key == "processes":
                    self._processes_db = {p["id"]: p for p in data}
                elif key == "lexicon":
                    self._lexicon = data
                elif key == "materials":
                    self._materials = data
                elif key == "product_types":
                    self._product_types = data
                elif key == "features":
                    self._features_db = data

    def _load_json(self, relative_path: str) -> Any:
        path = self._dir / relative_path
        with open(path, encoding="utf-8") as f:
            return json.load(f)

    # ------------------------------------------------------------------
    # Product name parsing
    # ------------------------------------------------------------------

    def parse_product(self, product_name: str) -> Optional[InferredProduct]:
        """Parse a product name into structured attributes.

        Works for ANY product name by matching known keywords.
        Falls back to sensible defaults when attributes are not recognized.
        """
        name = product_name.strip().lower()
        words = name.replace("-", " ").replace(",", "").split()

        material_id = self._extract_material(name, words)
        type_id, type_info = self._extract_product_type(name, words)
        features = self._extract_features(name, words)
        gender = self._extract_gender(name, words)

        if type_id is None:
            return None

        fabric_structure = self._determine_fabric_structure(
            material_id, type_info
        )
        category = type_info.get("category", "Garments")

        return InferredProduct(
            raw_name=product_name.strip(),
            material_id=material_id,
            product_type_id=type_id,
            product_type_name=type_info.get("name", type_id.replace("_", " ").title()),
            category=category,
            gender=gender,
            detected_features=features,
            fabric_structure_determined=fabric_structure,
        )

    def _extract_material(self, name: str, words: list[str]) -> Optional[str]:
        """Extract material ID from product name using lexicon."""
        entries = self._lexicon.get("material_keywords", [])
        for entry in entries:
            for pattern in entry["words"]:
                if pattern in name:
                    return entry["material_id"]
        return None

    def _extract_product_type(self, name: str, words: list[str]) -> tuple[Optional[str], dict]:
        """Extract product type ID from product name using lexicon and fuzzy fallback."""
        entries = self._lexicon.get("product_type_keywords", [])
        best_match = None
        best_len = 0

        # 1. Multi-word keyword match (e.g. "t-shirt", "polo shirt")
        for entry in entries:
            for pattern in entry["words"]:
                if pattern in name and len(pattern) > best_len:
                    best_match = entry["type_id"]
                    best_len = len(pattern)

        if best_match and best_match in self._product_types:
            return best_match, self._product_types[best_match]

        # 2. Single-word match
        for word in words:
            for entry in entries:
                for pattern in entry["words"]:
                    if word == pattern and entry["type_id"] in self._product_types:
                        return entry["type_id"], self._product_types[entry["type_id"]]

        # 3. Fuzzy fallback — match any word against any known product type name
        best_ratio = 0.0
        best_fuzzy_id = None
        for word in words:
            for tid, tinfo in self._product_types.items():
                for comparable in [tinfo["name"].lower(), tid.lower()]:
                    ratio = SequenceMatcher(None, word, comparable).ratio()
                    if ratio > best_ratio:
                        best_ratio = ratio
                        best_fuzzy_id = tid

        if best_ratio >= 0.6 and best_fuzzy_id:
            return best_fuzzy_id, self._product_types[best_fuzzy_id]

        return None, {}

    def _extract_features(self, name: str, words: list[str]) -> list[str]:
        """Extract feature IDs from product name using lexicon."""
        detected: list[str] = []
        entries = self._lexicon.get("feature_keywords", [])
        for entry in entries:
            for pattern in entry["words"]:
                if pattern in name:
                    detected.append(entry["feature_id"])
                    break
        return detected

    def _extract_gender(self, name: str, words: list[str]) -> Optional[str]:
        """Extract gender from product name."""
        for gender, keywords in self._lexicon.get("gender_keywords", {}).items():
            for kw in keywords:
                if kw in name:
                    return gender
        return None

    def _determine_fabric_structure(self, material_id: Optional[str], type_info: dict) -> str:
        """Determine fabric structure (knitted/woven) based on material and product type.

        The product type's default takes precedence over the material's structure,
        because the same material (e.g. cotton) can be knitted (jersey) or woven
        (poplin) depending on the garment type.
        """
        default = type_info.get("processes", {}).get("default_material_structure", "woven")
        if material_id and material_id in self._materials:
            return self._materials[material_id].get("fabric_structure", default)
        return default

    # ------------------------------------------------------------------
    # Workflow inference
    # ------------------------------------------------------------------

    def _get_effective_features(self, product: InferredProduct) -> set[str]:
        """Combine type-typical features with name-detected features.

        Product types define typical features (e.g. jeans have zippers,
        buttons, pockets). These are used as defaults. Any features
        explicitly mentioned in the product name are added on top.
        """
        type_info = self._product_types.get(product.product_type_id, {})
        typical = set(type_info.get("typical_features", []))
        detected = set(product.detected_features)
        return typical | detected

    def infer_workflow(self, product: InferredProduct) -> list[ManufacturingProcess]:
        """Infer the complete ordered manufacturing workflow for a product."""
        type_info = self._product_types.get(product.product_type_id, {})
        type_processes = type_info.get("processes", {})
        material_info = self._materials.get(product.material_id) if product.material_id else None

        effective_features = self._get_effective_features(product)

        # Collect all required process IDs
        process_ids: list[str] = list(type_processes.get("mandatory_ids", []))

        # Add material-triggered processes
        material_triggered = type_processes.get("material_triggered", {})
        structure = product.fabric_structure_determined
        if structure in material_triggered:
            self._extend_unique(process_ids, material_triggered[structure])

        if product.material_id == "denim" and "denim_specific" in material_triggered:
            self._extend_unique(process_ids, material_triggered["denim_specific"])

        if material_info:
            process_ids.extend(material_info.get("special_processes", []))

        # Add special material-based sewing processes
        if material_info and material_info.get("fabric_structure") == "knitted":
            if "fabric_relaxation" not in process_ids:
                process_ids.append("fabric_relaxation")

        if product.material_id == "denim":
            if "washing" not in process_ids:
                process_ids.append("washing")
            if "drying" not in process_ids:
                process_ids.append("drying")

        # Add feature-triggered processes (type defaults + name-detected)
        for feature_id in effective_features:
            if feature_id == "printing":
                if "printing" not in process_ids:
                    process_ids.append("printing")
            elif feature_id == "embroidery":
                if "embroidery" not in process_ids:
                    process_ids.append("embroidery")
            elif feature_id == "stone_wash":
                if "sandblasting" not in process_ids:
                    process_ids.append("sandblasting")
            elif feature_id in self._features_db:
                extra = self._features_db[feature_id].get("processes", [])
                self._extend_unique(process_ids, extra)

        # Deduplicate while preserving order
        seen: set[str] = set()
        ordered_ids: list[str] = []
        for pid in process_ids:
            if pid not in seen:
                seen.add(pid)
                ordered_ids.append(pid)

        # Build full process objects with machines
        workflow = []
        for pid in ordered_ids:
            if pid in self._processes_db:
                process = self._build_process(pid, product, material_info)
                if process:
                    workflow.append(process)

        workflow.sort(key=lambda p: p.sequence)
        return workflow

    def _build_process(
        self, process_id: str, product: InferredProduct,
        material_info: Optional[dict]
    ) -> Optional[ManufacturingProcess]:
        """Build a ManufacturingProcess with machines filtered by context."""
        pdata = self._processes_db.get(process_id)
        if not pdata:
            return None

        all_machine_ids = pdata.get("machine_ids", [])
        machines = self._select_machines(
            process_id, all_machine_ids, product, material_info
        )

        return ManufacturingProcess(
            id=pdata["id"],
            name=pdata["name"],
            description=pdata.get("description", ""),
            sequence=pdata.get("sequence", 99),
            optional=pdata.get("optional", False),
            machines=machines,
        )

    def _select_machines(
        self, process_id: str, machine_ids: list[str],
        product: InferredProduct, material_info: Optional[dict]
    ) -> list[Machine]:
        """Select appropriate machines based on product context."""
        if not machine_ids:
            return []

        machines = []
        for mid in machine_ids:
            mdata = self._machines_db.get(mid)
            if not mdata:
                continue

            if process_id == "sewing":
                if self._is_sewing_machine_relevant(mid, mid, product):
                    machines.append(self._dict_to_machine(mid, mdata))
            elif process_id == "fabric_cutting":
                if self._is_cutting_machine_relevant(mid, material_info):
                    machines.append(self._dict_to_machine(mid, mdata))
            elif process_id == "ironing":
                if self._is_ironing_machine_relevant(mid, product, material_info):
                    machines.append(self._dict_to_machine(mid, mdata))
            else:
                machines.append(self._dict_to_machine(mid, mdata))

        return machines

    def _is_sewing_machine_relevant(self, mid: str, _: str, product: InferredProduct) -> bool:
        """Determine if a sewing machine is relevant for this product's material/features."""
        material_info = self._materials.get(product.material_id) if product.material_id else None
        material_sewing = material_info.get("sewing_methods", []) if material_info else []

        machine_name = self._machines_db.get(mid, {}).get("name", "").lower()
        machine_mapping = {
            "overlock machine": "overlock",
            "single needle lockstitch machine": "lockstitch",
            "flatlock machine": "flatlock",
            "interlock stitch machine": "interlock",
            "button hole machine": "button_hole",
            "button stitch machine": "button_stitch",
            "zipper attachment machine": "zipper_attachment",
            "bartack machine": "bartack",
            "feed-off-the-arm machine": "feed_off_arm",
            "snap fastener machine": "snap_fastener",
            "elastic attachment machine": "elastic_attachment",
            "blind stitch machine": "blind_stitch",
        }

        method = None
        for name_key, method_key in machine_mapping.items():
            if name_key in machine_name:
                method = method_key
                break

        if method is None:
            return True

        # Check if material supports this sewing method
        if material_sewing and method not in material_sewing:
            return False

        # Feature-based filtering using type-typical + name-detected features
        type_info = self._product_types.get(product.product_type_id, {})
        typical_features = set(type_info.get("typical_features", []))
        detected_features = set(product.detected_features)
        effective_features = typical_features | detected_features

        feature_machine_map = {
            "buttons": {"button_hole", "button_stitch"},
            "zipper": {"zipper_attachment"},
            "pockets": {"bartack"},
            "belt_loops": {"bartack"},
            "elastic_waist": {"elastic_attachment"},
            "hood": {"feed_off_arm"},
            "neck_rib": {"feed_off_arm"},
            "rivets": {"snap_fastener"},
            "snaps": {"snap_fastener"},
        }

        for feature_id, required_methods in feature_machine_map.items():
            if method in required_methods:
                if feature_id not in effective_features:
                    return False

        return True

    def _is_cutting_machine_relevant(self, mid: str, material_info: Optional[dict]) -> bool:
        """Determine if a cutting machine is suitable for the material."""
        if not material_info:
            return True

        cutting_methods = material_info.get("cutting_methods", [])
        if not cutting_methods:
            return True

        machine_name = self._machines_db.get(mid, {}).get("name", "").lower()
        mapping = {
            "cnc fabric cutter": "cnc",
            "straight knife cutting machine": "straight_knife",
            "band knife machine": "band_knife",
            "die cutting machine": "die_cutting",
            "laser cutting machine": "laser",
        }

        method = None
        for name_key, method_key in mapping.items():
            if name_key in machine_name:
                method = method_key
                break

        if method and method not in cutting_methods:
            return False
        return True

    def _is_ironing_machine_relevant(self, mid: str, product: InferredProduct, material_info: Optional[dict]) -> bool:
        """Determine if an ironing machine is suitable for the material."""
        if mid != "M032":
            return True

        if product.material_id == "silk":
            return True

        if material_info:
            special = material_info.get("special_processes", [])
            if "finishing_tunnel" in special:
                return True

        return False

    def _dict_to_machine(self, mid: str, mdata: dict) -> Machine:
        return Machine(
            id=mid,
            name=mdata["name"],
            category=mdata.get("category", ""),
            description=mdata.get("description", ""),
            purpose=mdata.get("purpose", ""),
            automation=mdata.get("automation", "Manual"),
            applications=mdata.get("applications", []),
        )

    @staticmethod
    def _extend_unique(target: list[str], items: list[str]) -> None:
        for item in items:
            if item not in target:
                target.append(item)
