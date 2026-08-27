"""Core platform package — domain-agnostic manufacturing intelligence.

The core owns ingestion, twin lifecycle (interface only — the twin object itself
is Workstream 2), reasoning orchestration, the generic carbon *engine*,
explainability, and APIs. **No industry knowledge lives here.** All material
lexicons, regex patterns, process rules, and carbon-calculation *models* belong
to a domain pack (`domain_packs/<domain>/`) and are reached only through the
:class:`~app.core.contracts.DomainPack` contract.

This keeps the "core never changes per industry" guarantee of Workstream 1: when
a new industry (EV battery, furniture) arrives, the core is untouched; a new
pack + new knowledge-repo contents are added and registered.
"""
