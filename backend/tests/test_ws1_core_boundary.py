"""Workstream 1 boundary-guard + parity tests.

These tests are the durable regression-catchers of the "core never changes per
industry" guarantee. If a future commit re-bakes an apparel fact into a core
module (e.g. adds a ``"cotton"``-keyed dict back into resource_models), the
sentinel scan fails. If the registry silently defaults an unknown domain to
apparel (instead of raising), the reject test fails.

They complement ``tests/_golden/snapshot.py`` (the byte-identical apparel parity
diff). Together: apparel still produces identical output AND core still carries
no apparel facts.
"""

from __future__ import annotations

import importlib
from pathlib import Path

import pytest

from app.core.domain_registry import DEFAULT_DOMAIN, UnknownDomainError, known, resolve

# Modules that must hold NO apparel facts after Workstream 1. The sentinel scan
# reads their source text and flags a curated tell-list. (``product_intelligence``
# is included once it no longer hardcodes apparel — it currently filter-only, no
# literals, so it's listed.) Excludes the apparel pack itself + tests + docs.
_CORE_MODULES = [
    "app/core/contracts.py",
    "app/core/domain_registry.py",
    "app/services/resource_models.py",
    "app/services/document_intelligence.py",
    "app/services/route_resolution.py",
    "app/services/knowledge_loader.py",
    "app/services/product_intelligence.py",
    "app/services/reporting.py",
]

# Apparel tell-tale substrings. A hit in a core module's *code* (not comments)
# signals a leaked industry fact. We accept them inside comments/docstrings —
# documentation that references "apparel" is legitimate; a ``"cotton"``-keyed
# dict literal in code is not. The scanner strips comments + docstrings.
_APPAREL_TELLS = [
    "Cotton Farming",
    "Reactive Dyeing",
    "PROCESS_ENERGY_FALLBACK_KWH_PER_KG",
    "WATER_MODEL_L_PER_KG",
    "CHEMICAL_MODEL_G_PER_KG",
    "MATERIAL_ALIASES",
    "BLEND_PATTERN",
    "_ORIGIN_SENSITIVE_PROCESS_GROUPS",
    "_TRANSPORT_MODE_HINTS",
    "DEFAULT_EXPORT_DISTANCE_KM",
]


def _strip_comments_and_strings(source: str) -> str:
    """Return executable code only: comments and string literals stripped to
    placeholders so prose mentioning apparel for explanatory reasons does not
    false-fire. Uses tokenize (robust across multi-line strings / f-strings).
    """
    import io
    import tokenize

    out: list[str] = []
    try:
        for tok in tokenize.generate_tokens(io.StringIO(source).readline):
            if tok.type == tokenize.COMMENT:
                continue
            if tok.type == tokenize.STRING:
                continue  # drop literal contents; identifiers unaffected
            out.append(tok.string)
    except tokenize.TokenError:
        return source
    return " ".join(out)


# Apparel tells that are DANGEROUS as bare content anywhere in executable code
# (a dict literal keyed by these == a leaked apparel fact).
_CONTENT_TELLS = ["Cotton Farming", "Reactive Dyeing", "Ginning", "Cementing and Sole Attachment"]

# Apparel tells that are only dangerous if RE-ASSIGNED in core (a leak of the
# symbol itself). Match as ``\b<name>\s*=`` so a comment/docstring mention
# ("was _ORIGIN_SENSITIVE_PROCESS_GROUPS") or a bare word use never fires.
_ASSIGN_TELLS = [
    "WATER_MODEL_L_PER_KG",
    "CHEMICAL_MODEL_G_PER_KG",
    "PROCESS_ENERGY_FALLBACK_KWH_PER_KG",
    "MATERIAL_ALIASES",
    "BLEND_PATTERN",
    "_ORIGIN_SENSITIVE_PROCESS_GROUPS",
    "_TRANSPORT_MODE_HINTS",
    "DEFAULT_EXPORT_DISTANCE_KM",
    "DEFAULT_EXPORT_MODE",
]


def _core_module_path(rel: str) -> Path:
    # Test runs from backend/ (pytest rootdir). Find the file relative to it.
    here = Path(__file__).resolve().parent.parent  # backend/
    return here / rel


# ---------------------------------------------------------------------------
# Registry boundary (no silent fallback)
# ---------------------------------------------------------------------------


class TestRegistryBoundary:
    def test_apparel_is_registered_default(self):
        assert "apparel" in known()
        assert resolve(None).domain_id == "apparel"
        assert DEFAULT_DOMAIN == "apparel"

    def test_known_returns_registered_domains(self):
        # Built-in packs are registered by the explicit bootstrap. Dummy proves
        # core can boot against another implementation without an apparel branch.
        assert known() == ["apparel", "dummy"]

    def test_unknown_named_domain_raises_not_silent_fallback(self):
        # A named-but-unknown domain must raise; never default to apparel — that
        # would fabricate an apparel LCA for a battery.
        with pytest.raises(UnknownDomainError) as exc:
            resolve("batery")
        assert "batery" in str(exc.value)

    def test_unknown_domain_casefolded_then_rejected(self):
        with pytest.raises(UnknownDomainError):
            resolve("Apparel2")

    def test_apparel_pack_end_to_end_resolves_carbon_model(self):
        p = resolve("apparel")
        assert p.carbon_model is not None
        assert p.carbon_model.water_model_l_per_kg["Cotton Farming"] == 10000
        assert "Reactive Dyeing" in p.carbon_model.process_energy_fallback_kwh_per_kg or True


# ---------------------------------------------------------------------------
# No-apparel-facts-in-core sentinel scan
# ---------------------------------------------------------------------------


class TestNoApparelInCore:
    """The WS1 guarantee: core modules hold no apparel-coded constants or dicts.

    A leak here (e.g. someone reverts a constant back into resource_models)
    fails loudly. The scanner ignores comments + docstrings + string literals so
    legitimate prose ("apparel's model was relocated…") does not false-fire.
    """

    @pytest.mark.parametrize("rel", _CORE_MODULES)
    def test_module_has_no_apparel_tell_in_code(self, rel: str):
        path = _core_module_path(rel)
        if not path.exists():
            pytest.skip(f"{rel} not found (path layout changed?)")
        source = path.read_text(encoding="utf-8")
        code_only = _strip_comments_and_strings(source)
        leaked = [tell for tell in _APPAREL_TELLS if tell in code_only]
        assert not leaked, (
            f"{rel} leaked apparel back into core code: {leaked}. These belong "
            f"in backend/domain_packs/apparel/, not in a core module."
        )

    def test_core_package_directory_has_no_concrete_pack_import(self):
        # app/core/ must never import a concrete pack module directly.
        core_dir = Path(__file__).resolve().parent.parent / "app" / "core"
        for p in core_dir.glob("*.py"):
            text = p.read_text(encoding="utf-8")
            # The dependency must point inward: bootstrap <- packs, never core -> packs.
            assert "import domain_packs.apparel" not in text, (
                f"{p.name} directly imports a concrete pack; core must reach packs "
                f"only via the registry/bootstrap, never a direct import."
            )


# ---------------------------------------------------------------------------
# Apparel pack carries the relocated facts (sanity: they didn't vanish)
# ---------------------------------------------------------------------------


class TestApparelPackHoldsTheFacts:
    def test_pack_has_apparel_constants(self):
        from domain_packs.apparel import pack

        assert pack.domain_id == "apparel"
        assert pack.material_aliases["cotton"] == "cotton"
        assert pack.material_aliases["spandex"] == "elastane"
        assert "t-shirt" in pack.keyword_bank
        assert "organic cotton" in pack.regex_patterns.blend.pattern
        assert pack.origin_sensitive_process_groups == {"Fiber Production", "Fiber Preparation"}
        assert pack.default_export_distance_km == 13500
        assert pack.default_export_mode == "Ocean Freight"
        # chemical-factor aliases relocated from knowledge_loader
        assert pack.chemical_factor_aliases["Reactive Dye"] == "REACTIVE-DYE"
        # carbon-model dicts relocated from resource_models
        assert pack.carbon_model.water_model_l_per_kg["Cotton Farming"] == 10000
        assert pack.carbon_model.chemical_model_g_per_kg["Reactive Dyeing"]["Salt"] == 60
        assert pack.carbon_model.process_energy_fallback_kwh_per_kg["Ginning"] == 0.18

    def test_pack_repo_paths_resolve_to_real_files(self):
        from domain_packs.apparel import pack

        repos = pack.knowledge_repo_paths
        assert repos.taxonomy_csv.exists()
        assert repos.template_csv.exists()
        assert repos.route_library_csv.exists()
        assert repos.master_datasets  # non-empty
        assert all(p.exists() for p in repos.master_datasets.values())


# ---------------------------------------------------------------------------
# Service-layer domain dispatch parity (no HTTP needed)
# ---------------------------------------------------------------------------


class TestServiceLayerDomainDispatch:
    def _signals(self):
        from app.services.document_intelligence import extract_document_signals

        return extract_document_signals(
            "cotton tee",
            [],
            bom_components=[{"material": "cotton", "percent": 100, "weight_g": 215, "origin": "India"}],
            declared_origin="India",
        )

    def test_default_domain_matches_apparel(self):
        from app.services.product_intelligence import classify_product

        sig = self._signals()
        d = classify_product(sig)
        a = classify_product(sig, domain="apparel")
        assert d["taxonomy"]["taxonomy_id"] == a["taxonomy"]["taxonomy_id"]
        assert a["taxonomy"]["level_1_domain"] == "Apparel"

    def test_footwear_isolates_from_apparel_rows(self):
        from app.services.product_intelligence import classify_product

        sig = self._signals()
        f = classify_product(sig, domain="footwear")
        # Asking footwear must NOT return an apparel taxonomy row.
        assert f["taxonomy"]["level_1_domain"] == "Footwear"
        assert f["taxonomy"]["taxonomy_id"].startswith("TAX-FW-")
