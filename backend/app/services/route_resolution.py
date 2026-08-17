"""Composite route resolution — derive the process flow from a product by its
composite signature (product type × material composition × origin), not
taxonomy-id alone.

Why this layer exists: ``match_template`` resolved a single ``default_route_id``
per taxonomy_id, so two products of the same class always got the *identical*
route regardless of material blend or origin — the collisions that make the LCA
process flow look static. The Route Library already declares, per route, a
pipe-list ``taxonomy_ids`` (which products it can serve) **and an
``inference_triggers`` column** (e.g. ``"cotton|organic cotton|BCI cotton|
seed cotton"``) naming the materials/contexts the route is authored for. This
module asks "which routes cover THIS taxonomy?" and then scores them by how
well they fit THIS BOM's composition and origin, choosing the best fit and
falling back to the template's ``default_route_id`` when nothing more specific
wins (the hybrid routing model: composite-key routing over existing routes; a
route-ASSEMBLY engine for uncovered cases is a later milestone).

Determinism / reuse: identical ``(taxonomy_id, composition, origin)`` returns the
identical route. The resolver memoizes its result by the composite signature so
the second run for the same inputs is free and never varies — the reuse
guarantee.
"""
from __future__ import annotations

from functools import lru_cache
from typing import Any, Iterable

from app.services.document_intelligence import BOMComponent, DocumentSignals
from app.services.knowledge_loader import load_knowledge_graph, load_master_data


# Origin-sensitive process groups ARE the raw-material-recovery steps whose
# country should follow the BOM origin (was a module-level apparel set). Now
# sourced from the resolved domain pack (apparel) so this core module holds no
# industry values. Same semantics as resource_models._resolve_pack.


def _resolve_pack():
    """Resolve the default domain pack for origin-sensitive process groups."""
    from domain_packs.bootstrap import bootstrap

    bootstrap()
    from app.core.domain_registry import resolve

    return resolve(None)


def _composition_tokens(blend: list[dict] | None,
                        bom_components: Iterable[BOMComponent] | None) -> set[str]:
    """Lowercased material tokens seen in the BOM (for matching inference_triggers)."""
    tokens: set[str] = set()
    for entry in blend or []:
        name = str(entry.get("material") or entry.get("name") or "").strip().lower()
        if name:
            tokens.add(name)
    for comp in bom_components or []:
        name = (comp.material or "").strip().lower()
        if name:
            tokens.add(name)
    return tokens


def _primary_origin(declared_origin: str | None,
                    bom_components: Iterable[BOMComponent] | None,
                    material_origins_by_material: dict | None,
                    materials_by_name: dict | None) -> str | None:
    """Resolve the strongest available origin signal for the BOM.

    Precedence: declared (aggregate) origin > per-component origin > the most
    confident material_origins row for the BOM's primary material (looked up via
    the materials master by name). Returns None when nothing is known — callers
    keep the route's default_country in that case (no regression).
    """
    if declared_origin and declared_origin.strip():
        return declared_origin.strip()
    if bom_components:
        for comp in bom_components:
            if (comp.origin or "").strip():
                return comp.origin.strip()
            # Per-material provenance from the master when the component names a
            # material that has a known origin row.
            mid = (materials_by_name or {}).get((comp.material or "").strip().lower())
            for row in (material_origins_by_material or {}).get(mid, []):
                if (row.get("country") or "").strip():
                    return row["country"].strip()
    return None


def _origin_key(origin: str | None) -> str:
    return (origin or "").strip().lower()


def _route_default_countries(route_steps: list[dict[str, str]]) -> set[str]:
    """Distinct step default_countries a route touches (its origin footprint)."""
    return {(s.get("default_country") or "").strip().lower() for s in route_steps if s.get("default_country")}


def _signature(taxonomy_id: str, tokens: set[str], origin: str | None) -> tuple:
    """Hashable composite key for memoization: (taxonomy, frozenset(materials), origin)."""
    return (taxonomy_id, frozenset(sorted(tokens)), _origin_key(origin))


def _score_route(route_meta: dict[str, str],
                 route_steps: list[dict[str, str]],
                 tokens: set[str],
                 origin: str | None,
                 master_data: dict[str, object]) -> tuple[int, str]:
    """Score one candidate route against the BOM's composition + origin.

    Returns ``(score, basis)`` so the resolver (and its trace record) can show
    *why* a route won. Composition fit uses the route's ``inference_triggers``
    pipe-list; origin fit compares the BOM origin to the route's per-step
    default_country footprint.
    """
    triggers_raw = (route_meta.get("inference_triggers") or "").lower()
    triggers = {t.strip() for t in triggers_raw.split("|") if t.strip()}

    composition_hits = tokens & triggers
    composition_score = 0
    basis_parts: list[str] = []
    if triggers:
        # How well does this route's authored materials cover the BOM's materials?
        composition_score = len(composition_hits) * 10
        if not composition_hits and tokens:
            composition_score = -5  # route authored for different materials
        basis_parts.append(f"composition {len(composition_hits)}/{len(tokens)}")

    origin_score = 0
    if origin:
        okey = _origin_key(origin)
        foot = _route_default_countries(route_steps)
        if okey in foot:
            origin_score = 15  # route already operates in the BOM's country
            basis_parts.append(f"origin '{origin}' in route footprint")
        else:
            origin_score = 0
            basis_parts.append(f"origin '{origin}' not in route footprint")
    else:
        basis_parts.append("no BOM origin")

    return (composition_score + origin_score, "; ".join(basis_parts) or "no discriminators")


def _candidates(taxonomy_id: str) -> list[tuple[dict[str, str], list[dict[str, str]]]]:
    """All (route_meta, route_steps) covering this taxonomy_id, in stable order."""
    kg = load_knowledge_graph()
    by_id = kg["routes_by_id"]
    seen: set[str] = set()
    out: list[tuple[dict[str, str], list[dict[str, str]]]] = []
    for row in kg["routes_by_taxonomy"].get(taxonomy_id, []):
        rid = row["route_id"]
        if rid in seen:
            continue
        seen.add(rid)
        out.append((row, by_id.get(rid, [])))
    return out


def resolve_route(
    taxonomy_id: str,
    signals: DocumentSignals,
    *,
    default_route_id: str | None,
) -> dict[str, object]:
    """Pick the best route_id for this BOM's (product × composition × origin).

    Returns ``{route_id, derivation_basis, confidence_level, is_fallback,
    signature, candidates_seen}``. Falls back to ``default_route_id`` (the
    template's) when no composition/origin-differentiated route wins — the
    hybrid model's "reuse an authored route when nothing more specific applies".

    Memoized by composite signature: identical signature → identical route.
    """
    master = load_master_data()
    materials_by_name = {  # lowercase material_name -> material_id, for origin lookup
        (r.get("material_name") or r.get("name") or "").strip().lower(): r.get("material_id", "")
        for r in master["datasets"].get("materials", [])
        if r.get("material_name") or r.get("name")
    }
    tokens = _composition_tokens(signals.blend, signals.bom_components)
    origin = _primary_origin(signals.declared_origin, signals.bom_components,
                             master.get("material_origins_by_material"), materials_by_name)
    sig = _signature(taxonomy_id, tokens, origin)
    chosen = _resolve_signature(sig, taxonomy_id, default_route_id or "")
    return {**chosen, "signature": list(sig), "bom_origin": origin}


@lru_cache(maxsize=256)
def _resolve_signature(sig: tuple, taxonomy_id: str, default_route_id: str) -> dict[str, object]:
    """Cached inner resolver. Per-signature: enumerate candidates, score, pick."""
    tokens = set(sig[1])
    origin = sig[2] or None
    master = load_master_data()

    candidates = _candidates(taxonomy_id)
    if not candidates:
        return {"route_id": default_route_id, "derivation_basis": "no routes cover taxonomy; template default",
                "confidence_level": "L4", "is_fallback": True, "candidates_seen": 0}

    scored: list[tuple[int, str, str, dict[str, str]]] = []
    for route_meta, route_steps in candidates:
        score, basis = _score_route(route_meta, route_steps, tokens, origin, master)
        scored.append((score, basis, route_meta["route_id"], route_meta))
    scored.sort(key=lambda t: (t[0], t[2]), reverse=True)
    best_score, best_basis, best_rid, best_meta = scored[0]

    # Fallback: if the best composite score is non-positive (no composition or
    # origin discriminator favoured a route over its siblings), keep the
    # template's reviewed default_route_id when it's among the candidates — this
    # preserves authored routing for the common case and only overrides when a
    # route genuinely fits the BOM better.
    fallback_ids = {default_route_id}
    if best_score <= 0 and default_route_id in {rid for _, _, rid, _ in scored}:
        return {"route_id": default_route_id,
                "derivation_basis": "fell back to template default route (no composition/origin win)",
                "confidence_level": "L4", "is_fallback": True, "candidates_seen": len(scored)}

    # A clear authored-composite win is L3 (trade): the route was authored for
    # this material/region and the BOM matches it. Honest, not assumed-primary.
    level = "L3" if best_score > 0 else "L4"
    return {"route_id": best_rid, "derivation_basis": best_basis,
            "confidence_level": level, "is_fallback": False,
            "candidates_seen": len(scored)}


def resolve_origin_context(signals: DocumentSignals) -> dict[str, object] | None:
    """Resolve the BOM origin so resource_models can inject it into origin-sensitive
    steps (farming/agro) without re-deriving it. Returns None when nothing known.
    """
    master = load_master_data()
    materials_by_name = {
        (r.get("material_name") or r.get("name") or "").strip().lower(): r.get("material_id", "")
        for r in master["datasets"].get("materials", [])
        if r.get("material_name") or r.get("name")
    }
    origin = _primary_origin(signals.declared_origin, signals.bom_components,
                             master.get("material_origins_by_material"), materials_by_name)
    if not origin:
        return None
    return {"origin": origin, "process_groups": _resolve_pack().origin_sensitive_process_groups}
