"""Dummy domain plugin used to prove the core can boot without Apparel logic.

It is a non-production pack: its only purpose is contract and bootstrap
validation. All of its synthetic knowledge and behavior stays inside this
package, so core never needs a Dummy- or Apparel-specific branch.
"""
from __future__ import annotations

from app.core.domain_registry import register
from domain_packs.dummy.knowledge import build_pack


def _build_and_register():
    pack = build_pack()
    register(pack.domain_id, lambda: pack)
    return pack


pack = _build_and_register()

__all__ = ["pack"]
