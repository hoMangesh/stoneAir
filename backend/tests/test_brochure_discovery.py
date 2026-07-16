"""Offline tests for the live brochure-discovery path.

Nothing here hits the network. The candidate-extraction tests monkeypatch
``urllib.request.urlopen`` to serve a checked-in DDG-HTML fixture; the
discovery contract tests patch it to raise so the never-hang / never-raise
behaviour is locked. Run with cwd = ``backend/`` so ``app.`` imports and the
masters CSVs resolve:

    .venv/bin/python -m pytest tests/test_brochure_discovery.py -q
"""
from __future__ import annotations

import io
import socket
import time
from contextlib import contextmanager
from unittest.mock import patch

import pytest

from app.services import brochure_discovery as bd


# ---------------------------------------------------------------------------
# Fixture HTML simulating modern DuckDuckGo result markup. Covers:
#   - a direct external PDF href (already caught by the old `_PDF_URL_RE`)
#   - a direct external HTML href (DROPPED by the old extractor — the key
#     regression this fix addresses)
#   - a `uddg=`-wrapped .gov PDF (kept via the unwrap branch)
#   - a DDG-internal `/l/?` nav link (must be filtered)
#   - a Yahoo sponsored ad (must be filtered)
#   - an alibaba ad (must be filtered)
#   - a relative `.js` asset (no scheme — must be filtered)
#   - a `result__url` whose text is truncated with ">" chevrons and no scheme
#     (best-effort fallback: must degrade to a host-level https URL, not the
#     deep PDF path)
# ---------------------------------------------------------------------------
_DDG_HTML_FIXTURE = """
<html><body>
<a class="result__a" href="https://www.polyestertime.com/wp-content/uploads/2016/05/Thies-iMaster-H2O.pdf">Thies iMaster H2O brochure</a>
<span class="result__url">polyestertime.com > wp-content > Thies-iMaster-H2O.pdf</span>
<a class="result__a" href="https://www.thies-gmbh.com/en/products/imaster-h2o">Thies GmbH iMaster H2O product page</a>
<span class="result__url">thies-gmbh.com > products > imaster-h2o</span>
<a class="result__a" href="//duckduckgo.com/l/?uddg=https%3A%2F%2Fwww.epa.gov%2Fsites%2Fproduction%2Ffiles%2F2020%2Fap42.pdf&rut=abc">EPA AP-42 reference</a>
<a class="result__a" href="/?q=more">More results</a>
<a href="https://r.search.yahoo.com/adclick">Sponsored</a>
<a href="https://www.alibaba.com/buy/">Buy now</a>
<a href="/static/js/app.js">app.js</a>
</body></html>
"""


class _FakeResponse:
    """Minimal file-like object mimicking ``urlopen``'s context manager."""

    def __init__(self, payload: bytes):
        self._payload = payload

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def read(self) -> bytes:
        return self._payload

    def geturl(self) -> str:
        return "https://html.duckduckgo.com/html/"

    @property
    def status(self) -> int:
        return 200


def _patch_urlopen(payload: bytes):
    """Patch ``urllib.request.urlopen`` used inside brochure_discovery so any
    request (search or fetch) returns ``payload`` instead of hitting the web."""
    fake = _FakeResponse(payload)
    return patch.object(bd.urllib.request, "urlopen", return_value=fake)


# ---------------------------------------------------------------------------
# Test 1 — candidate extraction
# ---------------------------------------------------------------------------
def test_candidate_urls_extracts_real_and_gov_filters_internal():
    with _patch_urlopen(_DDG_HTML_FIXTURE.encode()):
        urls = bd._candidate_urls_from_search('"Thies iMaster H2O" filetype:pdf')

    brochure = "https://www.polyestertime.com/wp-content/uploads/2016/05/Thies-iMaster-H2O.pdf"
    gov_pdf = "https://www.epa.gov/sites/production/files/2020/ap42.pdf"
    html_page = "https://www.thies-gmbh.com/en/products/imaster-h2o"

    # Direct external PDF and the uddg-unwrapped .gov PDF must survive.
    assert brochure in urls
    assert gov_pdf in urls
    # The direct external HTML page is the key regression — the old extractor
    # dropped it because it was neither `.pdf` nor `.gov`.
    assert html_page in urls

    joined = " ".join(urls)
    # Internal nav / sponsored / ads / schemeless assets must be filtered out.
    assert "duckduckgo.com" not in joined
    assert "r.search.yahoo.com" not in joined
    assert "alibaba.com" not in joined
    assert "amazon.com" not in joined
    assert "app.js" not in joined
    # No schemeless / relative links leak through.
    assert all(u.startswith(("http://", "https://")) for u in urls)

    # The truncated `result__url` must reconstruct to a clean, "/"-delimited
    # https URL (chevrons restored to slashes). It should not contain the raw
    # ">" chevrons or spaces that would make it un-fetchable.
    degraded = [u for u in urls if u.startswith("https://polyestertime.com")]
    assert degraded, "truncated result__url should reconstruct to an https URL"
    for u in degraded:
        assert ">" not in u
        assert " " not in u

    # Dedup: the brochure appears once.
    assert urls.count(brochure) == 1


# ---------------------------------------------------------------------------
# Test 2 — per-strategy candidate ranking
# ---------------------------------------------------------------------------
def test_rank_candidates_prefers_pdf_for_brochure_strategy():
    url_pdf = "https://example.com/thies-brochure.pdf"
    url_html = "https://www.thies-gmbh.com/en/products/imaster-h2o"
    url_ad = "https://www.alibaba.com/buy/something"

    ranked = bd._rank_candidates([url_html, url_ad, url_pdf], "Manufacturer brochure")
    # The real PDF ranks first for a brochure strategy.
    assert ranked[0] == url_pdf
    # The ad ranks last (negative score).
    assert ranked[-1] == url_ad
    # HTML page is in between.
    assert ranked.index(url_pdf) < ranked.index(url_html) < ranked.index(url_ad)


def test_rank_candidates_prefers_gov_for_open_lca_strategy():
    url_gov = "https://www.epa.gov/sites/production/files/2020/ap42.pdf"
    url_pdf = "https://vendor.com/some-unrelated.pdf"
    # For a no-pdf (open-LCA) strategy, a .gov standards host should outrank a
    # generic .pdf — though both score; the .gov ties-break dominates via the
    # +50 gov bonus. Here `.gov` URL also ends in .pdf, so it scores highest.
    ranked = bd._rank_candidates([url_pdf, url_gov], "EPA AP-42 / openLCA")
    assert ranked[0] == url_gov


# ---------------------------------------------------------------------------
# Test 3 — offline derivation from synthetic brochure text
# ---------------------------------------------------------------------------
def test_derive_from_text_synthetic_brochure():
    text = (
        "Thies iMaster H2O\n"
        "Installed power: 18.0 kW\n"
        "Throughput: 120 kg/h\n"
    )
    kwh, power, throughput, basis = bd._derive_from_text(text)
    assert power == 18.0
    assert throughput == 120.0
    assert kwh == round(18.0 / 120.0, 4)  # 0.15
    assert "18.0" in basis or "18.00" in basis
    assert "120" in basis


def test_derive_from_text_returns_none_without_throughput():
    text = "Installed power: 18.0 kW\nno throughput figure here"
    kwh, power, throughput, basis = bd._derive_from_text(text)
    assert kwh is None
    assert power == 18.0
    assert throughput is None


# ---------------------------------------------------------------------------
# Test 6 — browser headers regression guard
# ---------------------------------------------------------------------------
def test_browser_headers_no_gzip():
    h = bd._browser_headers()
    assert h["Accept-Encoding"] == "identity"
    assert h["User-Agent"] in bd._BROWSER_UAS
    assert "text/html" in h["Accept"]
    assert h["Accept-Language"].startswith("en")


# ---------------------------------------------------------------------------
# Test 4 — cache hit makes NO network call (governance guard)
# ---------------------------------------------------------------------------
def _fake_master_with_approved_profile(machine_model_id: str, electricity: float) -> dict:
    return {
        "machine_energy_by_model": {
            machine_model_id: {
                "approval_status": "Brochure Approved",
                "electricity": electricity,
                "unit": "kWh/kg fabric",
                "source": "unit-test fixture",
            }
        },
        "datasets": {
            "machine_models": [
                {
                    "machine_model_id": machine_model_id,
                    "manufacturer": "Thies",
                    "model": "iMaster H2O",
                    "machine_category": "Jet Dyeing Machine",
                }
            ]
        },
    }


def test_discover_energy_cache_hit_no_network():
    mid = "thies-imaster-h2o-test"
    master = _fake_master_with_approved_profile(mid, 0.15)
    with patch.object(bd, "load_master_data", return_value=master) as lm, \
         patch.object(bd.urllib.request, "urlopen") as urlopen:
        result = bd.discover_energy(mid)
    assert result.cache_hit is True
    assert result.derived_kwh_per_unit == 0.15
    # A cache hit must never touch the network.
    assert urlopen.call_count == 0
    # load_master_data is consulted once for the Tier-0 check.
    assert lm.call_count == 1


# ---------------------------------------------------------------------------
# Test 5 — never raises and never hangs (contract guard)
# ---------------------------------------------------------------------------
def test_discover_energy_never_raises_and_caps_time():
    mid = "thies-imaster-h2o-test"
    # A master where this model resolves (so we reach the ladder) but is NOT a
    # Tier-0 cache hit (no "Brochure Approved" profile).
    base = {
        "machine_energy_by_model": {
            mid: {"approval_status": "Pending Validation"},  # not approved -> cache miss
        },
        "datasets": {
            "machine_models": [
                {
                    "machine_model_id": mid,
                    "manufacturer": "Thies",
                    "model": "iMaster H2O",
                    "machine_category": "Jet Dyeing Machine",
                }
            ]
        },
    }

    def _boom(*args, **kwargs):
        raise socket.timeout("simulated flaky network")

    started = time.monotonic()
    with patch.object(bd, "load_master_data", return_value=base), \
         patch.object(bd.urllib.request, "urlopen", side_effect=_boom):
        result = bd.discover_energy(mid)
    elapsed = time.monotonic() - started

    # Never raises; returns a structured result.
    assert isinstance(result, bd.DiscoveryResult)
    assert result.cache_hit is False
    assert result.derived_kwh_per_unit is None
    # Some attempts were recorded (network_error / skipped).
    assert len(result.attempts) >= 1
    outcomes = {a.outcome for a in result.attempts}
    assert outcomes & {"network_error", "skipped"}
    # Never hangs: bounded by the hard cap (+ small grace for the final sleep).
    assert elapsed <= bd._TOTAL_TIMEOUT + 2.0
