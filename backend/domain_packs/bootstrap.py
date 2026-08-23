"""Pack bootstrap — imports every registered domain pack so core's
:func:`app.core.domain_registry.resolve` can serve them.

This is the one place that *knows which packs exist*. Core never imports a
concrete pack; it only imports (collections.abc-style) the bootstrap hook,
which then imports each pack whose registration side-effect populates the
registry. Adding an industry means adding one import line here — core stays
untouched, preserving the "core never changes per industry" guarantee.

Keeping this as a distinct module (rather than leaning on import side-effects
elsewhere) makes the registration point explicit, greppable, and idempotent.
"""

from __future__ import annotations

_BOOTSTRAPPED = False


def bootstrap() -> None:
    """Import the registered packs so they register with the core registry.

    Idempotent — safe to call from ``main.py`` startup, ``conftest.py``, and
    inside :func:`load_master_data`'s default path; the cost is one no-op after
    the first call.
    """
    global _BOOTSTRAPPED
    if _BOOTSTRAPPED:
        return
    # Each import has a side-effect: the pack's __init__ builds and registers
    # itself. Importing here (not in core) keeps the dependency direction purely
    # inward — core depends on the contract; the bootstrap depends on the packs.
    import domain_packs.apparel  # noqa: F401  (registration side-effect)
    import domain_packs.dummy  # noqa: F401  (contract-validation plugin)
    _BOOTSTRAPPED = True


__all__ = ["bootstrap"]
