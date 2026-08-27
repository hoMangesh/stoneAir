"""Domain packs — per-industry plug-ins under the Workstream 1 core contract.

Each subpackage is one industry (``apparel``, ``ev_battery`` …) exposing a
:class:`app.core.contracts.DomainPack`. A runtime bootstrap imports the
registered packs so :func:`app.core.domain_registry.resolve` can serve them.
"""
