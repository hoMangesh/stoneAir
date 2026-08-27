"""SDK dry-run pack: synthetic, generic, and intentionally not production knowledge."""
from domain_sdk import register_domain_plugin
from domain_packs.sandbox.implementation import build_pack


pack = register_domain_plugin(build_pack)

__all__ = ["pack"]
