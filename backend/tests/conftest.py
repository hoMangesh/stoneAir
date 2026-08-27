"""Pytest bootstrap for the multi-domain core (Workstream 1).

Registering the available domain packs with the core registry is an import
side-effect of each pack's ``__init__``. We trigger that once at collection so
``resolve("<domain>")`` succeeds in any test — even those that touch the
registry directly rather than going through ``load_master_data``.

Adding an industry later is one extra import line in
:mod:`domain_packs.bootstrap`; this conftest keeps the same one-line call.
"""
from domain_packs.bootstrap import bootstrap

bootstrap()
