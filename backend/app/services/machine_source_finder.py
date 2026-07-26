"""General machine-source finder (Step 4b, Phase 1).

Replaces the brand-bound ``_OFFICIAL_DOMAINS`` + ``build_query_strings`` approach
with a discovery + authority-scoring pipeline keyed on **machine identity**
``{manufacturer, model, category, process}`` — so any machine, in any industry,
can find an authoritative source without a hand-coded brand list.

Three deterministic candidate paths, none a single point of failure:
  1. registered brochure URLs already on file (most authentic rung once recorded),
  2. manufacturer official-site crawl — *generalized*: resolve a domain by DNS +
     reachability probe (no hand-list), then a bounded 1-hop crawl (reuses
     ``brochure_discovery._official_site_candidates``),
  3. entity-grounded multi-engine search across ≥2 hosts (reuses the DDG + Bing
     HTML parsers), so one captcha/bot-block downgrades instead of aborting.

Every candidate becomes a scored ``Source`` (authority tier, not a boolean
allow-list) so unseen industries are judged by signals, not membership. The finder
returns sources only; fetching + derivation stay in ``brochure_discovery`` so the
``DiscoveryResult``/``DiscoveryAttempt`` response shape (locked by the API + tests)
is untouched.
"""
from __future__ import annotations

import socket
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass, field

from app.services import brochure_discovery as bd


# ---------------------------------------------------------------------------
# Authority model — ranked, not allow-listed.
# ---------------------------------------------------------------------------
# Tiers are *positive trust signals*; the reject set is the *generic* thing we
# never want (resellers / SEO / aggregator / piracy), so an unseen industry isn't
# mis-trusted just because we typed its brand once. Trust derives from signals:
# does this host plausibly belong to the manufacturer, or is it a known spec
# publisher, or a government/standards body?

TIER_MANUFACTURER = "manufacturer"   # official site of the machine's maker
TIER_PUBLISHER = "publisher"         # recognised spec/datasheet publisher
TIER_GOV_STANDARDS = "gov-standards"  # .gov / energystar / eprel / iso / iop
TIER_GENERAL = "general"             # anything else that isn't rejected

_SCORE_MANUFACTURER = 200
_SCORE_PUBLISHER = 120
_SCORE_GOV = 90
_SCORE_GENERAL = 10
_SCORE_PDF = 100
_SCORE_SPEC_TOKEN = 30
_SCORE_REJECT = -400

# Known spec/datasheet publishers — an editable registry, not a code constant.
# Lower trust than the manufacturer's own site, higher than generic search hits.
_SPEC_PUBLISHER_HOSTS = (
    "lectura-specs", "machinerytrader", "specguideonline", "manufacturing.net",
    "industrial machinery", "thomasnet", "directindustry", "industryabout",
)

# Generic reject set — a marketplace/reseller/aggregator/SEO/piracy site is never
# an authentic primary source even when it happens to host a keyword. Massively
# broader than the old 5-token ``_MARKETING_BLOCKLIST`` (which remains in
# brochure_discovery for the legacy crawl; the finder also applies this one).
_REJECT_HOST_TOKENS = (
    "alibaba.com", "amazon.com", "amazon.", "ebay.", "ebay.com", "aliexpress.com",
    "made-in-china.com", "madeinchina.com", "dhgate.com",
    "indiamart.com", "tradeindia.com", "ec21.com",
    "scribd.com", "slideshare.com", "issuu.com", "yumpu.com", "scribbr.com",
    "wikipedia.org", "wikimedia.org", "youtube.com", "youtu.be", "tiktok.com",
    "facebook.com", "instagram.com", "pinterest.com", "twitter.com", "x.com",
    "reddit.com", "quora.com", "zhihu.com", "52pojie.cn", "52pojie.com",
    "medium.com", "blogspot.com", "wordpress.com", "weebly.com", "tnsp.com",
    "pirated", "crack", "torrent", "mega.nz", "mediafire.com",
    "/buy/", "/shop/", "/cart", "/product/category", "/deals/",
)

_GOV_STANDARDS_HOST_TOKENS = (
    ".gov", "energystar", "eprel", "energy.gov", "nrel", ".iso.org", "iso.org",
    "iopscience", "sciencedirect", "springer", "ieee", "doi.org", ".epa.",
)

_SPEC_PATH_TOKENS = ("spec", "datasheet", "data-sheet", "brochure", "manual", "techn",
                     "catalogue", "catalog", "product")


@dataclass
class Source:
    url: str
    host: str
    tier: str
    score: int
    basis: str
    kind: str = "search"   # "registered" | "official_crawl" | "search"


@dataclass
class MachineIdentity:
    manufacturer: str = ""
    model: str = ""
    category: str = ""
    process: str = ""

    @property
    def subject(self) -> str:
        """The scoped phrase queries and crawling key off (brand + model)."""
        return " ".join(p for p in (self.manufacturer, self.model) if p).strip()


# ---------------------------------------------------------------------------
# Manufacturer-domain resolution — generalized, no hand-list.
# ---------------------------------------------------------------------------
# A small override map for the known-apparel brands (corrected: Thies's real
# textile-machinery site). This is a *hint*, not the sole source of truth: when
# no override exists we *discover* a plausible brand domain and probe it.

_MANUFACTURER_DOMAIN_HINTS = {
    "thies": "thies-textilmaschinen.de",   # corrected: thies-gmbh.com does not resolve
    "mayer & cie": "mayercie.com",
    "mayer": "mayercie.com",
    "rieter": "rieter.com",
    "juki": "juki.com",
}


def _manuf_domain_from_name(manufacturer: str) -> str | None:
    """Best-effort brand domain from the manufacturer name (no external lookup).

    Strips common legal suffixes and returns the obvious domain guess so the
    official crawl has a starting point for brands we don't know. Returns None
    for an empty manufacturer (then the official-crawl path is skipped and we
    rely on search).
    """
    name = (manufacturer or "").strip().lower()
    if not name:
        return None
    for hint_key, domain in _MANUFACTURER_DOMAIN_HINTS.items():
        if hint_key in name:
            return domain
    for suffix in (" gmbh", " gmbh&co", " gmbh & co", " kg", " ltd", " limited",
                   " inc", " corp", " corporation", " co.", " co", " pty",
                   " s.r.l", " s.a.", " s.a", " ag", "& cie", " and cie", "&cie"):
        if name.endswith(suffix):
            name = name[: -len(suffix)].strip()
    name = name.replace("&", "and").replace(" ", "")
    if not name:
        return None
    return f"{name}.com"


def _host_reachable(host: str, *, timeout: float = 1.5) -> bool:
    """Cheap liveness check: is this host DNS-resolvable right now? Never raises.

    We only need to know whether a domain *exists* before committing fetch budget
    to it (the old path crawled an unreachable ``thies-gmbh.com`` and wasted a
    full strategy budget on a DNS error). A bare DNS lookup is enough; an HTTP
    probe is done later by the crawl itself.
    """
    try:
        socket.gethostbyname(host)
        return True
    except socket.gaierror:
        return False
    except OSError:
        return False


# ---------------------------------------------------------------------------
# Scoring — judge a found URL's authority by signals, not membership.
# ---------------------------------------------------------------------------

def _score_source(url: str, identity: MachineIdentity, *, kind: str = "search") -> Source:
    """Score one candidate URL into a tiered Source by authority signals."""
    parsed = urllib.parse.urlparse(url)
    host = (parsed.netloc or "").lower()
    path = (parsed.path or "").lower()
    lowered = url.lower()

    if _is_rejected(host, path):
        return Source(url, host, TIER_GENERAL, _SCORE_REJECT, "rejected (reseller/aggregator/SEO)", kind)

    tier, base, basis = TIER_GENERAL, _SCORE_GENERAL, "general web hit"
    manuf_domain = _manuf_domain_from_name(identity.manufacturer)
    if manuf_domain and manuf_domain in host:
        tier, base, basis = TIER_MANUFACTURER, _SCORE_MANUFACTURER, f"official site ({manuf_domain})"
    elif any(tok in host for tok in _GOV_STANDARDS_HOST_TOKENS):
        tier, base, basis = TIER_GOV_STANDARDS, _SCORE_GOV, "gov/standards body"
    elif any(tok in host for tok in _SPEC_PUBLISHER_HOSTS):
        tier, base, basis = TIER_PUBLISHER, _SCORE_PUBLISHER, "spec publisher"

    score = base
    if lowered.endswith(".pdf") or ".pdf?" in lowered or ".pdf#" in lowered:
        score += _SCORE_PDF
    if any(tok in path for tok in _SPEC_PATH_TOKENS):
        score += _SCORE_SPEC_TOKEN

    return Source(url, host, tier, score, basis, kind)


def _is_rejected(host: str, path: str) -> bool:
    """True if this host/path is a marketplace/reseller/aggregator/SEO/piracy site.

    Domain-shaped tokens (``"x.com"``, ``"ebay."``, ...) are matched against the
    host at a registrable-name boundary so ``"x.com"`` rejects ``x.com`` and
    ``twitter.x.com`` but NOT ``zortex.com`` (a naive substring test would
    falsely reject ``zorte**x.com**``). Path-shaped tokens (``"/buy/"`` etc.)
    are matched against the path.
    """
    # Path-level reject tokens.
    for tok in _REJECT_HOST_TOKENS:
        if tok.startswith("/") and tok in path:
            return True
    # Host-level reject tokens: match the bare registrable name or any subdomain of it.
    bare = host.removeprefix("www.")
    for tok in _REJECT_HOST_TOKENS:
        if tok.startswith("/"):
            continue
        tok_clean = tok.strip(".")
        if not tok_clean:
            continue
        if bare == tok_clean or bare.endswith("." + tok_clean):
            return True
    return False


def _dedupe_scored(sources: list[Source]) -> list[Source]:
    seen: set[str] = set()
    out: list[Source] = []
    for s in sources:
        key = s.url.split("#", 1)[0]
        if s.score <= _SCORE_REJECT or key in seen:
            continue
        seen.add(key)
        out.append(s)
    # Highest authority first; deterministic tie-break by url.
    out.sort(key=lambda s: (s.score, s.url), reverse=True)
    return out


# ---------------------------------------------------------------------------
# Query construction — entity-grounded, multi-engine.
# ---------------------------------------------------------------------------

def build_queries(identity: MachineIdentity) -> list[tuple[str, str]]:
    """Authority-ordered search queries grounded in the machine identity.

    Each targets real data files or databases, bypassing marketing pages.
    """
    subject = identity.subject or identity.category
    if not subject:
        return []
    qs: list[tuple[str, str]] = [
        ("Manufacturer brochure", f'"{subject}" filetype:pdf "specification sheet"'),
        ("Manufacturer datasheet", f'"{subject}" "power consumption" "specification"'),
        ("Technical documentation", f'"{subject}" "technical data" "operating manual" filetype:pdf'),
        ("Spec publisher", f'"{subject}" datasheet "installed power" OR "throughput"'),
        ("Government efficiency DB", f'"{subject}" site:.gov efficiency filetype:pdf'),
        ("Open LCA", f'"{identity.category}" "emission factor" OR "energy" AP-42 OR openLCA filetype:pdf'),
    ]
    # Restrict the brochure query to the brand's own domain when we can resolve it.
    manuf_domain = _manuf_domain_from_name(identity.manufacturer)
    if manuf_domain:
        qs.insert(0, ("Manufacturer official", f'"{subject}" site:{manuf_domain} filetype:pdf'))
    return qs


# ---------------------------------------------------------------------------
# Public finder.
# ---------------------------------------------------------------------------

def find_candidate_sources(
    identity: MachineIdentity,
    *,
    registered_urls: list[tuple[str, str]] | None = None,
    deadline: float,
) -> tuple[list[Source], list[str]]:
    """Return ``(authority-ranked candidate sources, search-host notes)``.

    ``registered_urls`` is [(brochure_id, url), ...] already on file
    (from machine_brochures.csv) — the most authentic rung, fetched first.
    ``deadline`` is a monotonic hard cap shared with the discovery ladder;
    every path respects it so analyze never hangs on a flaky source.

    ``notes`` carries honest search-host observations (e.g. a DDG captcha page
    that forced a Bing fallback) so the caller can record them as
    ``DiscoveryAttempt`` entries with the legacy vocabulary.

    Never raises. Returns whatever was collected when the deadline hits.
    """
    def _remaining() -> float:
        return max(0.5, deadline - time.monotonic())

    scored: list[Source] = []

    # 1. Registered brochure URLs (real ones only; TBD_* seeds are the caller's job to skip).
    registered_seen: list[str] = []
    for _brochure_id, url in registered_urls or []:
        if url.lower().startswith(("http://", "https://")):
            scored.append(_score_source(url, identity, kind="registered"))
            registered_seen.append(url)

    # 2. Manufacturer official-site crawl — generalized: probe the (hinted/guessed)
    #    brand domain by DNS; only crawl if it actually resolves. Reuses the
    #    bounded 1-hop crawl already implemented in brochure_discovery.
    official_crawl_urls: list[str] = []
    manuf_domain = _manuf_domain_from_name(identity.manufacturer)
    if manuf_domain and _host_reachable(manuf_domain) and _remaining() > 0.5:
        official_crawl_urls = bd._official_site_candidates(identity.manufacturer, identity.model,
                                                           deadline=deadline)
        for url in official_crawl_urls:
            if _remaining() <= 0.5:
                break
            scored.append(_score_source(url, identity, kind="official_crawl"))

    # 3. Entity-grounded multi-engine search. DDG first; if it's bot-gated (captcha
    #    page) or empty, the SAME query retries on Bing before the next strategy —
    #    a single blocked host never strands discovery.
    notes: list[str] = []
    for _strategy, query in build_queries(identity):
        if _remaining() <= 0.5:
            break
        ddg_urls, ddg_html = bd._ddg_candidates(query, timeout=min(bd._SEARCH_TIMEOUT, _remaining()))
        urls = ddg_urls
        if not urls:
            if bool(ddg_html) and bd._looks_like_captcha(ddg_html):
                notes.append("DuckDuckGo captcha/anomaly page; falling back to Bing")
            if _remaining() > 0.5:
                urls = bd._candidate_urls_from_bing(query, timeout=min(bd._SEARCH_TIMEOUT, _remaining()))
        for url in urls:
            scored.append(_score_source(url, identity, kind="search"))

    return _dedupe_scored(scored), notes
