"""Domain-pack registry — resolves a ``domain`` string to its :class:`DomainPack`.

The registry is the single place core asks "which pack?". Everything else
threads a resolved pack down the pipeline. Unknown domains raise
:class:`UnknownDomainError` explicitly — **never a silent apparel fallback** —
so a mis-typed ``domain=batery`` fails loudly rather than silently producing an
apparel LCA for a battery (a hallucination hiding in the system, against the
Workstream 4 reasoning-service principle already enforced at the boundary).

Packs register lazily via a provider callable (``Callable[[], DomainPack]``).
The provider indirection keeps the import graph acyclic: a pack module imports
core contract types to *build* a pack, then registers itself on first import of
this module — so the core never imports a concrete pack at module load time.
"""

from __future__ import annotations

from collections.abc import Callable
from functools import lru_cache

from app.core.contracts import DomainPack


DEFAULT_DOMAIN = "apparel"


class UnknownDomainError(KeyError):
    """Raised when ``domain`` resolves to no registered pack.

    Subclasses :class:`KeyError` so existing ``except KeyError`` sites still
    catch it if ever needed, but its ``str()`` names the offending domain so the
    API can surface a precise error (``{"detail": "unknown domain: 'batery'"}``).
    """

    def __str__(self) -> str:  # type: ignore[override]
        return f"unknown domain: {super().__str__()}"


# domain_id -> provider returning the singleton pack. Dict (not lru_cache on
# resolve) so registration can happen at import time without a cache key collision.
_PROVIDERS: dict[str, Callable[[], DomainPack]] = {}
# Materialized singletons so a provider is called at most once per process.
_PACKS: dict[str, DomainPack] = {}


def register(domain_id: str, provider: Callable[[], DomainPack]) -> None:
    """Register a pack provider under ``domain_id`` (idempotent).

    ``provider`` builds and returns the :class:`DomainPack`; we materialize it
    once on first :func:`resolve`. Re-registering the same ``domain_id`` with a
    different provider overwrites (lets a pack module be re-imported in tests
    without "already registered" noise), but the previously materialized
    singleton is dropped so the new provider takes effect.
    """
    _PROVIDERS[domain_id] = provider
    _PACKS.pop(domain_id, None)


def known() -> list[str]:
    """Return the sorted registered domain ids (for catalog/health endpoints)."""
    return sorted(_PROVIDERS)


def resolve(domain: str | None = None) -> DomainPack:
    """Resolve ``domain`` to its pack. ``None``/empty → the default pack.

    Raises :class:`UnknownDomainError` if ``domain`` is set but unregistered —
    never falls back to the default for a *named-but-unknown* domain, so a typo
    cannot silently mislead.
    """
    domain_id = (domain or "").strip().lower() or DEFAULT_DOMAIN
    if domain_id not in _PROVIDERS:
        raise UnknownDomainError(domain_id)
    if domain_id not in _PACKS:
        _PACKS[domain_id] = _PROVIDERS[domain_id]()
    return _PACKS[domain_id]


@lru_cache(maxsize=1)
def _default_pack() -> DomainPack:
    """Cache the default pack so repeated ``resolve(None)`` is free."""
    return resolve(DEFAULT_DOMAIN)


__all__ = [
    "DEFAULT_DOMAIN",
    "UnknownDomainError",
    "register",
    "known",
    "resolve",
]
