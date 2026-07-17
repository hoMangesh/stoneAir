"""Live machine-energy discovery from the web at analyze time.

Goal: replace industry-average energy proxies with near-exact figures derived
from authentic public sources, so the carbon estimate approaches reality.

Resolution ladder (authenticity high -> low), in order:

  0. DB / masters cache hit — an already-promoted brochure-derived energy
     profile exists for the model. Instant, no network. This is why promotion
     matters: the second run for the same machine is free.
  1. Manufacturer brochure on the official company site (genuine, public).
  2. Manufacturer technical docs — data sheets / spec manuals / O&M manuals /
     Factory Acceptance Test (FAT) data.
  3. Government & regulatory efficiency databases — EPREL (EU), US DOE
     Compliance Certification, ENERGY STAR certified equipment.
  4. Open industrial standards & open-source LCA — US EPA AP-42, openLCA Nexus
     (Agribalyse / Federal LCA Commons).

Discovery uses precise search strings to bypass marketing pages and reach real
data files, e.g.
   "[Brand] [Model]" filetype:pdf "specification sheet"
   "[Brand] [Model]" "power consumption" "cycle time"
   "[Machine type]" site:.gov efficiency database

Robustness contract: EVERY network/parse failure downgrades to the next
strategy and ultimately returns None. discover_energy() never raises and never
blocks the caller longer than `total_timeout`. When it returns None the carbon
engine keeps using the existing KG-proxy energy profile, so analyze never
breaks or hangs on a flaky web source.
"""
from __future__ import annotations

import random
import re
import socket
import time
import urllib.parse
import urllib.request
from dataclasses import dataclass, field
from typing import Iterable

from app.services.knowledge_loader import load_master_data
from app.services.brochure_pipeline import (
    _parse_power,
    _parse_throughput_kg_per_h,
    _CATEGORY_UNIT,
    persist_brochure_observations,
)


# ---------------------------------------------------------------------------
# Per-attempt and total budgets — "quick". Tuned so the worst case (every
# strategy fails) still returns inside a few seconds and never hangs analyze.
# ---------------------------------------------------------------------------
# The search request itself gets a *shorter* timeout than a doc fetch: a slow
# or blocked search precinct burns the budget and finds nothing, so we bail it
# fast and leave the remaining time for fetching real candidates. The hard
# total cap is a stated contract — _TOTAL_TIMEOUT never rises.
_SEARCH_TIMEOUT = 4.0             # the search-host HTML query must return fast
_PER_URL_TIMEOUT = 4.0            # seconds per candidate URL fetch
_TOTAL_TIMEOUT = 12.0             # hard cap across the whole discovery
_MAX_CANDIDATES_PER_STRATEGY = 2  # fetch at most this many PDFs per query
# Tier 0.5 official-site crawl: bound how deep we go so a single model's
# direct-official fetch can't blow the whole discovery budget.
_MAX_OFFICIAL_CRAWL_CANDIDATES = 4  # candidate URLs we'll fetch from the official site
_MAX_OFFICIAL_CRAWL_PAGES = 3       # HTML pages we'll fetch + parse for follow links


@dataclass
class DiscoveryAttempt:
    strategy: str
    query: str
    url: str | None
    outcome: str           # "derived" | "fetched_no_specs" | "network_error" | "parse_error" | "skipped"
    derived_kwh_per_unit: float | None
    installed_power_kw: float | None
    throughput_kg_per_h: float | None
    basis: str             # human-readable derivation basis
    notes: str = ""


@dataclass
class DiscoveryResult:
    machine_model_id: str
    derived_kwh_per_unit: float | None
    unit: str
    installed_power_kw: float | None
    throughput_kg_per_h: float | None
    cache_hit: bool            # True = served from DB-approved profile, no web
    attempts: list[DiscoveryAttempt] = field(default_factory=list)
    basis: str = ""


# ---------------------------------------------------------------------------
# Browser-like request headers.
# ---------------------------------------------------------------------------
# DuckDuckGo's HTML endpoint serves an "anomaly" (captcha) page to
# self-declaring bots; a realistic desktop UA gets real organic results. We
# rotate across a small list so a single UA getting rate-limited degrades
# per-request rather than globally.
#
# `Accept-Encoding: identity` is load-bearing: urllib.request does NOT
# transparently gunzip, so a browser UA (which makes hosts serve gzip)
# would arrive as compressed bytes and our regex would find nothing — the
# exact failure the bot UA produced, silently. Keep identity.
_BROWSER_UAS = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/605.1.15 (KHTML, like Gecko) Version/16.5 Safari/605.1.15",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Mozilla/5.0 (X11; Linux x86_64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
)


def _browser_headers() -> dict[str, str]:
    return {
        "User-Agent": random.choice(_BROWSER_UAS),
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "en-US,en;q=0.9",
        "Accept-Encoding": "identity",  # urllib doesn't gunzip
    }


# ---------------------------------------------------------------------------
# Query builder — produces the precise authority-ordered search strings.
# ---------------------------------------------------------------------------

def build_query_strings(model: dict) -> list[tuple[str, str]]:
    """Return a list of (strategy, query) pairs in authority order.

    Each query is crafted to bypass marketing pages and reach a real data file
    or government/standards database.
    """
    brand = (model.get("manufacturer") or "").strip()
    model_name = (model.get("model") or "").strip()
    category = (model.get("machine_category") or "").strip().lower()
    subject = f"{brand} {model_name}".strip() or category

    queries: list[tuple[str, str]] = []
    # 1. Manufacturer brochure / spec sheet on official site (filetype pdf).
    queries.append(("Manufacturer brochure", f'"{subject}" filetype:pdf "specification sheet"'))
    queries.append(("Manufacturer datasheet", f'"{subject}" "power consumption" "cycle time"'))
    # Restrict to the brand's own domain when we recognise it (genuinely official).
    brand_domain = _official_domain(brand)
    if brand_domain:
        queries.append(("Manufacturer official", f'"{subject}" site:{brand_domain} filetype:pdf'))
    # 2. Technical documentation / O&M / FAT.
    queries.append(("Technical documentation", f'"{subject}" "technical data" "operating manual" filetype:pdf'))
    # 3. Government / regulatory efficiency databases.
    queries.append(("EPREL/DOE/ENERGY STAR", f'"{subject}" site:.gov efficiency database'))
    queries.append(("Government efficiency DB", f'"{category}" site:.gov "energy" filetype:pdf'))
    # 4. Open industrial standards / open LCA.
    queries.append(("EPA AP-42 / openLCA", f'"{category}" "emission factor" "AP-42" OR "openLCA"'))
    return queries


_OFFICIAL_DOMAINS = {
    "thies": "thies-gmbh.com",
    "mayer & cie": "mayercie.com",
    "rieter": "rieter.com",
    "juki": "juki.com",
}


def _official_domain(brand: str) -> str | None:
    lowered = (brand or "").lower()
    for key, domain in _OFFICIAL_DOMAINS.items():
        if key in lowered:
            return domain
    return None


# ---------------------------------------------------------------------------
# Tier 0.5 — direct official source (no search dependency).
# ---------------------------------------------------------------------------
# The most authentic source in the ladder is the manufacturer's own brochure on
# its official site. Going through a search host to reach it is fragile (DuckDuckGo
# serves a captcha/anomaly page in many environments), so Tier 0.5 reaches it
# directly: first any brochure URL already registered in machine_brochures.csv,
# then a bounded 1-hop crawl of the brand's official domain. Both paths stay
# inside the hard _TOTAL_TIMEOUT cap and record honest attempt outcomes.

# Spec-bearing URL tokens; ranked higher in the official crawl.
_SPEC_TOKENS = ("spec", "datasheet", "data-sheet", "brochure", "manual", "product", "techn")


def _real_public_urls(machine_model_id: str, master: dict) -> list[tuple[str, str]]:
    """Registered brochure URLs for a model that are real URLs (skip TBD_* seeds).

    Returns ``[(brochure_id, public_url), ...]`` from machine_brochures.csv rows.
    Placeholders like ``TBD_PUBLIC_BROCHURE_REQUIRED`` are skipped — they carry
    the *intent* of a future URL, not an authentic source.
    """
    out: list[tuple[str, str]] = []
    for row in master.get("machine_brochures_by_model", {}).get(machine_model_id, []):
        url = (row.get("public_url") or "").strip()
        if url.lower().startswith(("http://", "https://")):
            out.append((row.get("brochure_id", ""), url))
    return out


def _looks_like_captcha(html: str) -> bool:
    """Detect a search-host anomaly/captcha page that yields no real results.

    A genuine DDG results page contains ``result__url`` elements; an anomaly/
    captcha page does not, and typically mentions "anomaly"/"unusual traffic".
    An empty-candidates run from any cause also reports False-ish here via the
    no-hrefs check below.
    """
    if not html:
        return True
    lowered = html.lower()
    if "result__url" in lowered:
        return False
    if "anomaly" in lowered or "unusual traffic" in lowered:
        return True
    return False


def _official_site_candidates(manufacturer: str, model_name: str, *, deadline: float) -> list[str]:
    """Bound the official-site fetch to ``deadline`` (monotonic). Harvest PDF
    + spec-bearing links from the official domain root, optionally following one
    hop into product/sitemap-style pages when the root exposes none. CNN.

    Returns ranked candidate URLs (PDFs + spec pages first). Never raises; on any
    failure or a blown deadline returns whatever was collected so far (possibly
    ``[]``).
    """
    domain = _official_domain(manufacturer or "")
    if not domain:
        return []

    def _remaining() -> float:
        return max(0.5, deadline - time.monotonic())

    root = f"https://{domain}/"
    root_html = _fetch_text(root, timeout=min(4.0, _remaining()))
    if not root_html or _remaining() <= 0.5:
        return []

    base = urllib.parse.urljoin(root, "/")
    seen: set[str] = set()
    candidate_pages: list[str] = []  # HTML pages worth a 1-hop follow
    ranked: list[str] = []

    def _rank_key(url: str) -> int:
        u = url.lower()
        s = 0
        if u.endswith(".pdf") or ".pdf?" in u or ".pdf#" in u:
            s += 100
        if any(t in u for t in _SPEC_TOKENS):
            s += 30
        if _is_obvious_adslead(url):
            s -= 200
        return s

    for href in _HREF_RE.findall(root_html):
        decoded = urllib.parse.unquote(href)
        absolute = urllib.parse.urljoin(base, decoded)
        if not absolute.lower().startswith(("http://", "https://")):
            continue
        if domain.lower() not in urllib.parse.urlparse(absolute).netloc.lower():
            continue  # stay on the official domain
        if _is_obvious_adslead(absolute):
            continue
        absolute = absolute.split("#", 1)[0]
        if absolute in seen:
            continue
        seen.add(absolute)
        low = absolute.lower()
        is_pdf = low.endswith(".pdf") or ".pdf?" in low or ".pdf#" in low
        # PDFs and explicit spec/datasheet/manual/brochure refs are end targets
        # (ranked); "product"-ish pages are NOT specs themselves — they're
        # follow-worthy hubs, so route them to the 1-hop candidates instead.
        # (Putting "product" in _SPEC_TOKENS starved the crawl: product pages
        # went to ranked, candidate_pages stayed empty, the hop never ran.)
        is_spec_ref = any(t in low for t in ("spec", "datasheet", "data-sheet", "brochure", "manual", "techn"))
        is_hub = any(seg in low for seg in ("product", "spinning", "knit", "sewing", "catalogue", "catalog"))
        if is_pdf or is_spec_ref:
            ranked.append(absolute)
        elif is_hub:
            candidate_pages.append(absolute)

    ranked.sort(key=_rank_key, reverse=True)

    # One hop: if the root had no direct PDF/spec links, fetch a few candidate
    # pages and harvest PDFs/spec links from THEM. Bounded by the deadline.
    if not any(u.lower().endswith(".pdf") for u in ranked):
        for page in candidate_pages[:_MAX_OFFICIAL_CRAWL_PAGES]:
            if _remaining() <= 0.5:
                break
            page_html = _fetch_text(page, timeout=min(4.0, _remaining()))
            if not page_html:
                continue
            page_base = page
            for href in _HREF_RE.findall(page_html):
                decoded = urllib.parse.unquote(href)
                absolute = urllib.parse.urljoin(page_base, decoded)
                low = absolute.lower()
                if not (low.endswith(".pdf") or ".pdf?" in low or ".pdf#" in low) and not any(t in low for t in _SPEC_TOKENS):
                    continue
                if domain.lower() not in urllib.parse.urlparse(absolute).netloc.lower():
                    continue
                if _is_obvious_adslead(absolute):
                    continue
                absolute = absolute.split("#", 1)[0]
                if absolute not in seen:
                    seen.add(absolute)
                    ranked.append(absolute)
            if len(ranked) >= _MAX_OFFICIAL_CRAWL_CANDIDATES:
                break

    return ranked[:_MAX_OFFICIAL_CRAWL_CANDIDATES]


# ---------------------------------------------------------------------------
# Candidate URL discovery — stdlib HTML search-host scraping.
# ---------------------------------------------------------------------------
# We avoid external search APIs (and their keys/rate-limits) by POSTing the
# precise query to a search engine's HTML endpoint and parsing <a href> links
# that point at .pdf / official / .gov URLs. This is fragile by nature (HTML
# changes), so every failure safely downgrades; the *fetch* and *extraction*
# stage is where real robustness lives.

# Every <a href="..."> anchor; we trust our own host filter rather than a
# fragile per-result CSS selector, since DDG's result markup changes.
_HREF_RE = re.compile(r'href="([^"]+)"', re.IGNORECASE)
# DDG redirect wrapper: "/l/?uddg=<encoded url>" or "?uddg=<encoded url>".
# Modern DDG points result anchors directly at the outbound URL, but the
# wrapped form still shows up for some result layouts — keep unwrapping it.
_UDDG_RE = re.compile(r'[?&]uddg=([^&"\']+)', re.IGNORECASE)
# DDG's "result__url" element shows the posted-as URL as visible text. It is
# often truncated with ">" chevrons and may lack a scheme, so it is a
# best-effort fallback, not a reliable deep link.
_RESULT_URL_RE = re.compile(r'class="result__url"[^>]*>\s*([^<]+?)\s*<', re.IGNORECASE)
# Hosts we never want as candidates (search-host internal nav/ads/sponsored).
_DDG_INTERNAL_HOSTS = (
    "duckduckgo.com", "duckduckgo.org", "r.search.yahoo.com",
    "bing.com", "go.microsoft.com",
)


def _is_ddg_internal(url: str) -> bool:
    try:
        host = urllib.parse.urlparse(url).netloc.lower()
    except ValueError:
        return True
    return any(h in host for h in _DDG_INTERNAL_HOSTS)


def _parse_ddg_candidates(html: str) -> list[str]:
    """Pure parser: external http(s) candidate URLs from a DDG results HTML.

    Source A: every external href (unwrapping the ``uddg=`` redirect); Source B:
    the ``result__url`` visible text (best-effort, ">"-chevron reconstructed).
    Filters search-internal nav and obvious ad links. Called both by the DDG
    wrapper (for the public list) and internally (to inspect the raw html for a
    captcha/anomaly page before falling back to Bing).
    """
    candidates: list[str] = []

    # Source A: every href that resolves to an external http(s) URL.
    for href in _HREF_RE.findall(html):
        decoded = urllib.parse.unquote(href)
        m = _UDDG_RE.search(decoded)
        if m:  # unwrap the DDG redirect target if the link is wrapped
            decoded = urllib.parse.unquote(m.group(1))
        if not decoded.lower().startswith(("http://", "https://")):
            continue
        if _is_ddg_internal(decoded) or _is_obvious_adslead(decoded):
            continue
        candidates.append(decoded)

    # Source B: result__url visible text (best-effort; often truncated/no-scheme).
    for um in _RESULT_URL_RE.finditer(html):
        url_text = um.group(1).strip()
        if not url_text:
            continue
        url_text = re.sub(r"\s*>\s*", "/", url_text)
        url_text = re.sub(r"\s+", "", url_text)
        if not url_text.lower().startswith(("http://", "https://")):
            url_text = "https://" + url_text
        if not _is_ddg_internal(url_text) and not _is_obvious_adslead(url_text):
            candidates.append(url_text)

    # Deduplicate preserving order; strip "#fragment" suffixes.
    seen: set[str] = set()
    unique: list[str] = []
    for url in candidates:
        url = url.split("#", 1)[0]
        if url and url not in seen:
            seen.add(url)
            unique.append(url)
    return unique


def _ddg_candidates(query: str, *, timeout: float = _SEARCH_TIMEOUT) -> tuple[list[str], str]:
    """Fetch DuckDuckGo's HTML results for ``query`` and return (urls, html).

    Returns ``([], "")`` on any network error. The raw html is kept so the caller
    can detect a captcha/anomaly page (``_looks_like_captcha``) and fall back to a
    second search host instead of silently yielding zero candidates.
    """
    safe_query = "+".join(urllib.parse.quote(part) for part in query.split())
    search_url = f"https://html.duckduckgo.com/html/?q={safe_query}&kl=us-en"
    try:
        req = urllib.request.Request(search_url, headers=_browser_headers())
        with urllib.request.urlopen(req, timeout=timeout) as response:  # noqa: S310 - public search
            html = response.read().decode("utf-8", errors="ignore")
    except (urllib.error.URLError, socket.timeout, TimeoutError, ConnectionError):
        return [], ""
    return _parse_ddg_candidates(html), html


def _candidate_urls_from_search(query: str, *, timeout: float = _SEARCH_TIMEOUT) -> list[str]:
    """Return candidate PDF/data URLs from a DuckDuckGo HTML query.

    Thin wrapper over ``_ddg_candidates`` keeping the original public contract
    (returns just the URL list) so existing callers/tests are unaffected.
    """
    urls, _html = _ddg_candidates(query, timeout=timeout)
    return urls


# Bing HTML search results expose the posted-as URL both as the ``<cite>``
# visible text under each result and (in some layouts) as a direct href on
# the result link. We harvest both and rely on our own host filter.
_BING_CITE_RE = re.compile(r'<cite[^>]*>(.*?)</cite>', re.IGNORECASE | re.DOTALL)


def _candidate_urls_from_bing(query: str, *, timeout: float = _SEARCH_TIMEOUT) -> list[str]:
    """Second search host (Bing HTML) used when DuckDuckGo is bot-gated.

    Returns external http(s) candidate URLs (PDF/spec pages preferred via ranking
    upstream), filtering search-internal and obvious ad links. On any error
    returns ``[]`` so the caller tries the next strategy. Mirrors
    ``_candidate_urls_from_search``'s contract but against a different host so a
    captcha/anomaly page from one host doesn't strand discovery entirely.
    """
    safe_query = "+".join(urllib.parse.quote(part) for part in query.split())
    search_url = f"https://www.bing.com/search?q={safe_query}"
    try:
        req = urllib.request.Request(search_url, headers=_browser_headers())
        with urllib.request.urlopen(req, timeout=timeout) as response:  # noqa: S310 - public search
            html = response.read().decode("utf-8", errors="ignore")
    except (urllib.error.URLError, socket.timeout, TimeoutError, ConnectionError):
        return []

    candidates: list[str] = []
    # Source A: external http(s) hrefs.
    for href in _HREF_RE.findall(html):
        decoded = urllib.parse.unquote(href)
        if not decoded.lower().startswith(("http://", "https://")):
            continue
        # Bing wraps result links through bing.com/.../...; keep only the host
        # a browser would land on by skipping obvious bing-internal hosts.
        if _is_ddg_internal(decoded) or _is_obvious_adslead(decoded):
            continue
        if "bing.com" in urllib.parse.urlparse(decoded).netloc.lower():
            continue
        candidates.append(decoded)
    # Source B: <cite> visible URL text under each result (best-effort).
    for cm in _BING_CITE_RE.finditer(html):
        raw = re.sub(r"<[^>]+>", "", cm.group(1)).strip()
        if not raw:
            continue
        raw = re.sub(r"\s+", "", raw)
        if not raw.lower().startswith(("http://", "https://")):
            raw = "https://" + raw
        if not _is_ddg_internal(raw) and not _is_obvious_adslead(raw) and "bing.com" not in urllib.parse.urlparse(raw).netloc.lower():
            candidates.append(raw)

    seen: set[str] = set()
    unique: list[str] = []
    for url in candidates:
        url = url.split("#", 1)[0]
        if url and url not in seen:
            seen.add(url)
            unique.append(url)
    return unique


_MARKETING_BLOCKLIST = (
    "/buy/", "/shop/", "/cart", "/product/category", "alibaba.com", "amazon.com",
)


def _is_obvious_adslead(url: str) -> bool:
    lowered = url.lower()
    return any(token in lowered for token in _MARKETING_BLOCKLIST)


def _rank_candidates(urls: list[str], strategy: str) -> list[str]:
    """Rank candidates so the most-likely-spec-bearing URL is fetched first.

    Within the tight per-strategy fetch budget this matters: a brochure
    ``filetype:pdf`` query should try the real PDF before a homepage, while a
    ``site:.gov`` query (HTML result pages) should prefer the standards host.
    """
    wants_pdf = "pdf" in strategy.lower() or "brochure" in strategy.lower()

    def score(url: str) -> int:
        u = url.lower()
        s = 0
        if u.endswith(".pdf") or ".pdf?" in u or ".pdf#" in u:
            s += 100
        if ".gov" in u or ".energystar" in u or "eprel" in u:
            s += 50
        if any(k in u for k in ("datasheet", "specification", "spec", "manual")):
            s += 20
        if any(b in u for b in _MARKETING_BLOCKLIST):
            s -= 200
        if not wants_pdf and not u.endswith(".pdf"):
            s += 10  # prefer HTML pages for the HTML-result strategies
        return s

    return sorted(urls, key=score, reverse=True)


# ---------------------------------------------------------------------------
# Fetch + extract — the robust stage. Every failure returns ("fetched_no_specs"
# or error) so discovery keeps moving.
# ---------------------------------------------------------------------------

def _fetch_text(url: str, *, timeout: float = _PER_URL_TIMEOUT) -> str | None:
    """Download a URL and return plain text (PDF -> pdfplumber, else utf-8)."""
    try:
        req = urllib.request.Request(url, headers=_browser_headers())
        with urllib.request.urlopen(req, timeout=timeout) as response:  # noqa: S310 - public docs
            raw = response.read()
    except (urllib.error.URLError, socket.timeout, TimeoutError, ConnectionError):
        return None
    if raw[:4] == b"%PDF":
        from app.services.document_intelligence import _extract_text_from_pdf
        return _extract_text_from_pdf(raw) or None
    try:
        return raw.decode("utf-8", errors="ignore")
    except UnicodeDecodeError:
        return None


def _derive_from_text(text: str) -> tuple[float | None, float | None, float | None, str]:
    """Return (kwh_per_unit, power_kw, throughput_kg_per_h, basis) from text."""
    power_kw, power_raw = _parse_power(text)
    throughput_kg_per_h, throughput_raw = _parse_throughput_kg_per_h(text)
    if power_kw and throughput_kg_per_h and throughput_kg_per_h > 0:
        kwh = round(power_kw / throughput_kg_per_h, 4)
        return kwh, power_kw, throughput_kg_per_h, f"{power_raw} / {throughput_raw} = {power_kw} kW / {throughput_kg_per_h} kg/h"
    if power_kw:
        return None, power_kw, None, f"{power_raw} found; no kg/h throughput -> cannot derive per-unit"
    return None, None, None, "no power figure found"


def _try_official_source(
    machine_model_id: str,
    model: dict,
    master: dict,
    *,
    deadline: float,
    attempts: list[DiscoveryAttempt],
) -> tuple[float, float, float, str, str, str | None] | None:
    """Tier 0.5: derive from the manufacturer's own site without a search host.

    1. Registered brochure URLs from machine_brochures.csv (skip TBD_* seeds)
       — the most authentic rung once a reviewer/Live-discovery has recorded one.
    2. A bounded 1-hop crawl of the brand's official domain (from
       _OFFICIAL_DOMAINS) harvesting PDF/spec links.

    On a real derivation returns ``(kwh, power_kw, throughput_kg_per_h, basis,
    url, brochure_id_or_None)``; the caller persists the observation. On any
    failure appends an honest attempt to ``attempts`` and returns ``None`` so the
    caller falls through to the search ladder. Never raises; respects the hard
    ``deadline`` (monotonic).
    """
    def _remaining() -> float:
        return max(0.5, deadline - time.monotonic())

    # 1. Registered public_url(s).
    registered = _real_public_urls(machine_model_id, master)
    for brochure_id, url in registered:
        if _remaining() <= 0.5:
            break
        text = _fetch_text(url, timeout=min(_PER_URL_TIMEOUT, _remaining()))
        if not text:
            attempts.append(DiscoveryAttempt("Official brochure URL", "", url, "network_error", None, None, None, ""))
            continue
        kwh, power_kw, throughput_kg_per_h, this_basis = _derive_from_text(text)
        if kwh is not None:
            attempts.append(DiscoveryAttempt("Official brochure URL", "", url, "derived", kwh, power_kw, throughput_kg_per_h, this_basis))
            return kwh, power_kw, throughput_kg_per_h, this_basis, url, brochure_id
        attempts.append(DiscoveryAttempt("Official brochure URL", "", url, "official_url_no_specs", None, power_kw, throughput_kg_per_h, this_basis))

    # 2. Bounded official-site 1-hop crawl.
    manufacturer = (model or {}).get("manufacturer") or ""
    model_name = (model or {}).get("model") or ""
    crawl_urls = _official_site_candidates(manufacturer, model_name, deadline=deadline)
    for url in crawl_urls:
        if _remaining() <= 0.5:
            break
        text = _fetch_text(url, timeout=min(_PER_URL_TIMEOUT, _remaining()))
        if not text:
            attempts.append(DiscoveryAttempt("Official-site crawl", "", url, "network_error", None, None, None, ""))
            continue
        kwh, power_kw, throughput_kg_per_h, this_basis = _derive_from_text(text)
        if kwh is not None:
            attempts.append(DiscoveryAttempt("Official-site crawl", "", url, "derived", kwh, power_kw, throughput_kg_per_h, this_basis))
            return kwh, power_kw, throughput_kg_per_h, this_basis, url, None
        attempts.append(DiscoveryAttempt("Official-site crawl", "", url, "official_crawl_no_specs", None, power_kw, throughput_kg_per_h, this_basis))

    if registered or crawl_urls:
        attempts.append(DiscoveryAttempt("Official source", "", None, "fetched_no_specs", None, None, None,
                                         "official source reached but no power+throughput derivation"))
    return None


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------

def discover_energy(machine_model_id: str) -> DiscoveryResult:
    """Resolve a near-exact energy figure for a machine model.

    Tier 0 (cache): a DB-approved energy profile already exists -> return it,
    mark cache_hit, no network, instant. This is the fast path after a model's
    brochure has been promoted once.
    Otherwise walk the authority ladder (brochure -> tech docs -> gov -> open
    LCA), fetching candidates and deriving kWh per unit. Returns the first
    derivation found, or None (leaving the KG proxy in place upstream).
    Never raises; never exceeds ~_TOTAL_TIMEOUT.
    """
    master = load_master_data()
    models = {m["machine_model_id"]: m for m in master["datasets"]["machine_models"]}
    model = models.get(machine_model_id)
    unit = _CATEGORY_UNIT.get((model or {}).get("machine_category", ""), "kWh/kg")

    # Tier 0: DB-approved cache hit.
    profile = master["machine_energy_by_model"].get(machine_model_id, {})
    if profile.get("approval_status") == "Brochure Approved" and profile.get("electricity"):
        return DiscoveryResult(
            machine_model_id=machine_model_id,
            derived_kwh_per_unit=float(profile["electricity"]),
            unit=profile.get("unit") or unit,
            installed_power_kw=None,
            throughput_kg_per_h=None,
            cache_hit=True,
            basis=f"DB-approved profile: {profile.get('source', '')}",
        )

    if not model:
        return DiscoveryResult(machine_model_id=machine_model_id, derived_kwh_per_unit=None, unit=unit,
                               installed_power_kw=None, throughput_kg_per_h=None, cache_hit=False)

    attempts: list[DiscoveryAttempt] = []
    started = time.monotonic()

    # ------------------------------------------------------------------
    # Tier 0.5: direct official source — the most authentic rung. Reach the
    # manufacturer's own brochure WITHOUT depending on a (fragile) search host.
    #   1. any brochure URL already registered in machine_brochures.csv
    #   2. a bounded 1-hop crawl of the brand's official domain
    # On a real derivation, persist the observation to machine_brochures.csv so
    # the next run reads the now-known URL instantly (Tier 0.5 reads it first).
    # ------------------------------------------------------------------
    tier05 = _try_official_source(machine_model_id, model, master, deadline=started + _TOTAL_TIMEOUT, attempts=attempts)
    if tier05 is not None:
        kwh, power_kw, throughput_kg_per_h, this_basis, url, brochure_id = tier05
        # Live derivation -> persist raw brochure observation (governance: only
        # the real power+throughput figures we actually fetched).
        try:
            persist_brochure_observations(
                machine_model_id,
                brochure_id=brochure_id,
                url=url,
                installed_power_kw=power_kw,
                throughput_kg_per_h=throughput_kg_per_h,
            )
        except Exception:
            # Persistence must never break discovery; the derivation still wins.
            pass
        return DiscoveryResult(
            machine_model_id=machine_model_id,
            derived_kwh_per_unit=kwh,
            unit=unit,
            installed_power_kw=power_kw,
            throughput_kg_per_h=throughput_kg_per_h,
            cache_hit=False,
            attempts=attempts,
            basis=this_basis,
        )

    derived: float | None = None
    final_power = final_throughput = None
    basis = ""

    for strategy, query in build_query_strings(model):
        # Hard wall-clock cap: never let discovery exceed _TOTAL_TIMEOUT, even if
        # individual urlopen timeouts misbehave. Bail to the KG proxy instead.
        elapsed = time.monotonic() - started
        if derived is not None or elapsed >= _TOTAL_TIMEOUT:
            break
        # Gentle spacing between strategies so repeated DDG queries look less
        # robotic and reduce ban risk (stays well inside the 12s budget).
        if attempts:
            time.sleep(0.25)
        remaining = max(0.5, _TOTAL_TIMEOUT - (time.monotonic() - started))
        ddg_urls, ddg_html = _ddg_candidates(query, timeout=min(_SEARCH_TIMEOUT, remaining))
        candidate_urls = _rank_candidates(ddg_urls, strategy)

        # Second-host fallback: if DuckDuckGo is bot-gated (captcha/anomaly page
        # with no results) or otherwise returned nothing, retry the SAME query on
        # Bing HTML before giving up on this strategy. A single captcha page must
        # never strand the whole discovery. Record the honest reason.
        if not candidate_urls:
            blocked = bool(ddg_html) and _looks_like_captcha(ddg_html)
            if blocked:
                attempts.append(DiscoveryAttempt(strategy, query, None, "search_host_blocked", None, None, None,
                                                  "DuckDuckGo captcha/anomaly page; falling back to Bing"))
            remaining = max(0.5, _TOTAL_TIMEOUT - (time.monotonic() - started))
            bing_urls = _candidate_urls_from_bing(query, timeout=min(_SEARCH_TIMEOUT, remaining))
            if bing_urls:
                candidate_urls = _rank_candidates(bing_urls, strategy)

        fetched = 0
        for url in candidate_urls[:_MAX_CANDIDATES_PER_STRATEGY]:
            if fetched >= _MAX_CANDIDATES_PER_STRATEGY or time.monotonic() - started >= _TOTAL_TIMEOUT:
                break
            remaining = max(0.5, _TOTAL_TIMEOUT - (time.monotonic() - started))
            text = _fetch_text(url, timeout=min(_PER_URL_TIMEOUT, remaining))
            fetched += 1
            if not text:
                attempts.append(DiscoveryAttempt(strategy, query, url, "network_error", None, None, None, ""))
                continue
            kwh, power_kw, throughput_kg_per_h, this_basis = _derive_from_text(text)
            if kwh is not None:
                attempts.append(DiscoveryAttempt(strategy, query, url, "derived", kwh, power_kw, throughput_kg_per_h, this_basis))
                derived = kwh
                final_power = power_kw
                final_throughput = throughput_kg_per_h
                basis = this_basis
                break
            attempts.append(DiscoveryAttempt(strategy, query, url, "fetched_no_specs", None, power_kw, throughput_kg_per_h, this_basis))
        if not candidate_urls and (not attempts or attempts[-1].outcome not in ("search_host_blocked",)):
            attempts.append(DiscoveryAttempt(strategy, query, None, "skipped", None, None, None, ""))

    return DiscoveryResult(
        machine_model_id=machine_model_id,
        derived_kwh_per_unit=derived,
        unit=unit,
        installed_power_kw=final_power,
        throughput_kg_per_h=final_throughput,
        cache_hit=False,
        attempts=attempts,
        basis=basis or "No derivation found; KG-proxy energy retained.",
    )
