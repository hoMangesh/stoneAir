"""Phase 1 tests for the general machine-source finder — all offline (no network).

These lock the new finder's generality + authority-scoring + reject-set behaviour.
They import the finder directly and score sources / patch the network primitives,
so nothing about them depends on a live search host.
"""
from __future__ import annotations

import socket
import urllib.error

import pytest

from app.services import machine_source_finder as mf
from app.services.machine_source_finder import (
    MachineIdentity,
    Source,
    TIER_MANUFACTURER,
    TIER_PUBLISHER,
    TIER_GOV_STANDARDS,
    TIER_GENERAL,
    _is_rejected,
    _manuf_domain_from_name,
    _score_source,
)


# ---------------------------------------------------------------------------
# Authority scoring — trust derives from signals, not brand membership.
# ---------------------------------------------------------------------------
def test_scoring_ranks_manufacturer_above_publisher_gov_and_resellers():
    identity = MachineIdentity(manufacturer="Mayer & Cie", model="Relanit", category="Circular Knitting Machine")

    manuf = _score_source("https://mayercie.com/relanit-datasheet.pdf", identity)
    pub = _score_source("https://lectura-specs.com/en/mayer-cie/relanit", identity)
    gov = _score_source("https://www.epa.gov/energy/textile-knitting", identity)  # plain .gov page (no PDF bonus)
    reseller = _score_source("https://www.alibaba.com/buy/relanit", identity)

    assert manuf.tier == TIER_MANUFACTURER
    assert pub.tier == TIER_PUBLISHER
    assert gov.tier == TIER_GOV_STANDARDS
    assert manuf.score > pub.score > gov.score
    assert reseller.score <= mf._SCORE_REJECT  # reseller rejected outright


def test_scoring_pdf_and_spec_token_bonuses_stacked():
    identity = MachineIdentity(manufacturer="Rieter", model="G 38")
    pdf_spec = _score_source("https://rieter.com/products/g38/datasheet.pdf", identity)
    plain_html = _score_source("https://rieter.com/about", identity)
    assert pdf_spec.tier == TIER_MANUFACTURER
    assert pdf_spec.score > plain_html.score
    # The brochure/spec PDF should outrank a manufacturer homepage.
    assert pdf_spec.score >= plain_html.score + mf._SCORE_PDF


# ---------------------------------------------------------------------------
# Generality — an identity with NO brand hint still gets scored candidates,
# and an unknown brand's domain is *guessed* (not required to be in a map).
# ---------------------------------------------------------------------------
def test_unknown_brand_gets_a_guessed_domain():
    # "Acme Widgets" is not in any brand map; the finder still derives a domain.
    assert _manuf_domain_from_name("Acme Widgets") == "acmewidgets.com"
    # Legal-suffix stripping keeps the guess clean.
    assert _manuf_domain_from_name("Some Machine GmbH") == "somemachine.com"
    assert _manuf_domain_from_name("Acme Ltd") == "acme.com"
    assert _manuf_domain_from_name("") is None


def test_finder_returns_candidates_for_unknown_brand(monkeypatch):
    # A machine no brand-list knows about, with search mocked to return a hit.
    identity = MachineIdentity(manufacturer="Zortex", model="Z-9 Loom", category="Weaving Machine")
    monkeypatch.setattr(mf.bd, "_ddg_candidates", lambda q, *, timeout: (["https://zortex.com/z9/spec.pdf"], ""))
    monkeypatch.setattr(mf.bd, "_candidate_urls_from_bing", lambda q, *, timeout: [])
    monkeypatch.setattr(mf, "_host_reachable", lambda host, *, timeout=1.5: False)  # skip the official crawl

    import time
    sources, _notes = mf.find_candidate_sources(identity, registered_urls=None, deadline=time.monotonic() + 10)
    assert sources, "finder must return candidates even for an unknown brand"
    top = sources[0]
    # The guessed-brand official domain beats a generic search hit.
    assert top.tier == TIER_MANUFACTURER, "guessed brand domain should be recognised as manufacturer-tier"
    assert top.url == "https://zortex.com/z9/spec.pdf"


# ---------------------------------------------------------------------------
# The expanded reject set drops the junk hosts the old ladder shipped.
# ---------------------------------------------------------------------------
def test_reject_set_drops_resellers_seo_aggregators_and_piracy():
    assert _is_rejected("www.alibaba.com", "/product/relanit")
    assert _is_rejected("zhihu.com", "/question/123")
    assert _is_rejected("www.52pojie.cn", "/thread/x")
    assert _is_rejected("scribd.com", "/doc/x")
    assert _is_rejected("en.wikipedia.org", "/wiki/Spinning")
    assert _is_rejected("www.made-in-china.com", "/g45")
    assert _is_rejected("twitter.com", "/x")  # short-host rejection without false-matching zortex.com
    # A legitimate manufacturer host is NOT rejected (regression guard: "x.com"
    # must not falsely match "zortex.com").
    assert not _is_rejected("zortex.com", "/z9/spec.pdf")
    assert not _is_rejected("rieter.com", "/products/g38.pdf")


def test_corrected_thies_domain_is_used_not_the_defunct_gmbh_one():
    # Must point at the real textile-machinery site, not the non-resolving thies-gmbh.com.
    assert _manuf_domain_from_name("Thies") == "thies-textilmaschinen.de"
    assert mf._MANUFACTURER_DOMAIN_HINTS["thies"] == "thies-textilmaschinen.de"


# ---------------------------------------------------------------------------
# HTTP fallback — https->http on a TLS failure (the broken-TLS Thies case).
# ---------------------------------------------------------------------------
def test_fetch_text_falls_back_to_http_on_https_tls_error(monkeypatch):
    from app.services import brochure_discovery as bd

    calls: list[str] = []

    class _SSLError(urllib.error.URLError):
        def __init__(self):
            super().__init__("[SSL: TLSV1_ALERT_INTERNAL_ERROR]")

    def _fake_urlopen(req, timeout=None):
        url = req.full_url
        calls.append(url)
        if url.startswith("https://"):
            raise _SSLError()
        class _R:
            def read(self_):
                return b"Thies iMaster H2O\nInstalled power: 18.0 kW\nThroughput: 120 kg/h\n"
            def __enter__(self_):
                return self_
            def __exit__(self_, *a):
                return False
        return _R()

    monkeypatch.setattr(bd.urllib.request, "urlopen", _fake_urlopen)
    text = bd._fetch_text("https://thies-textilmaschinen.de/imaster.pdf")
    assert text and "18.0 kW" in text, "TLS failure on https must fall back to http and still yield text"
    assert any(c.startswith("https://") for c in calls), "https attempt must be made first"
    assert any(c.startswith("http://") for c in calls), "http fallback must fire on https failure"


if __name__ == "__main__":
    pytest.main([__file__, "-q"])
