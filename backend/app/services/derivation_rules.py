"""Per-category energy derivation rules for machine brochure text.

Step 4b Phase 2. A single ``kW ÷ kg/h`` shape only serves spinning/knitting;
the real machine surface is many categories whose energy is batch×cycle,
feed×width, per-garment, or per-area. This module keys a derivation *rule*
by machine category, each rule a physics formula that yields the same
``Result`` (kwh_per_unit, unit, power, throughput, basis, confidence) the
legacy mass-rate shape returned.

Design rules (see plan ``gentle-riding-waterfall.md`` Phase 2):

- Each rule is a small pure function ``derive(text, parse) -> Result | None``.
  It uses the regexes already in :mod:`machine_intelligence` (passed in via
  ``parse`` so this module stays import-light and unit-testable without the
  network layer) plus ``parse.power``/``parse.throughput_kg_per_h``.
- A category-specific rule *falls back to mass-rate* when its own required
  fields are absent but a usable ``kW ÷ kg/h`` is present — a dyeing
  brochure that only quotes kg/h still derives, just via the generic shape.
  This keeps the locked 14 tests green and never loses a real derivation.
- The unknown rule is best-effort mass-rate flagged low-confidence; it never
  returns a silent high-conf proxy and never raises.
- ``derive_for_category`` is the dispatcher: pick the rule by category, the
  rule's own fallback chain handles the rest.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Callable, Optional, Protocol

from app.services import machine_intelligence as mi


# ---------------------------------------------------------------------------
# Parsing contract — the dispatcher hands each rule these helpers so rules
# stay decoupled from brochure_pipeline's I/O and are unit-testable in
# isolation (tests can monkeypatch `power`/`throughput_kg_per_h`).
# ---------------------------------------------------------------------------


class _Parse(Protocol):
    power: Callable[[str], tuple[Optional[float], str]]
    throughput_kg_per_h: Callable[[str], tuple[Optional[float], str]]


@dataclass(frozen=True)
class Result:
    """A derivation outcome. Mirrors the legacy 4-tuple plus a unit + confidence."""

    kwh_per_unit: float
    unit: str
    installed_power_kw: float
    throughput_kg_per_h: Optional[float]
    basis: str
    confidence: float
    rule_name: str


# A rule: (text, parse) -> Result | None.
Rule = Callable[[str, _Parse], Optional[Result]]


# ---------------------------------------------------------------------------
# Helpers shared by the rules
# ---------------------------------------------------------------------------


def _first(pattern: re.Pattern, text: str) -> Optional[dict]:
    """First match payload (value/unit/raw) or None."""
    for match in pattern.finditer(text):
        return {k: v for k, v in match.groupdict().items() if v is not None} | {"raw": match.group(0)}
    return None


def _to_hours(value: float, unit: str) -> float:
    """Normalise a cycle-duration unit into hours."""
    unit = (unit or "").lower().strip(".")
    if unit.startswith("h"):
        return value
    # min, mins, minutes (and bare 'm') -> hours
    return value / 60.0


def _to_meters(value: float, unit: str) -> float:
    """Normalise a width/speed length unit into metres."""
    unit = (unit or "").lower().strip(".")
    if unit == "cm":
        return value / 100.0
    if unit == "mm":
        return value / 1000.0
    # m, metre, meter, m/min variants already in metres
    return value


def _mass_rate_basis(power_kw: float, throughput_kg_per_h: float, power_raw, throughput_raw) -> str:
    return f"{power_raw} / {throughput_raw} = {power_kw} kW / {throughput_kg_per_h} kg/h"


# ---------------------------------------------------------------------------
# Rules
# ---------------------------------------------------------------------------


def rule_mass_rate(text: str, parse: _Parse) -> Optional[Result]:
    """Primary/general shape: kW ÷ kg/h. Covers Ring Frame, Circular Knitting,
    Stenter (when quoted as kg/h). The rule the original pipeline used and the
    fallback every category-specific rule degrades to."""
    power_kw, power_raw = parse.power(text)
    if not power_kw:
        return None
    throughput_kg_per_h, throughput_raw = parse.throughput_kg_per_h(text)
    if not throughput_kg_per_h or throughput_kg_per_h <= 0:
        return None
    return Result(
        kwh_per_unit=round(power_kw / throughput_kg_per_h, 4),
        unit="kWh/kg",
        installed_power_kw=power_kw,
        throughput_kg_per_h=throughput_kg_per_h,
        basis=_mass_rate_basis(power_kw, throughput_kg_per_h, power_raw, throughput_raw),
        confidence=0.8,
        rule_name="mass-rate",
    )


def rule_batch_cycle(text: str, parse: _Parse) -> Optional[Result]:
    """Batch processes (Jet Dyeing, Washing, Pre-treatment, Finishing baths):
    ``installed_kW × cycle_hours ÷ batch_kg`` -> ``kWh/kg fabric``.

    Falls back to mass-rate when batch/cycle figures are absent but a kg/h
    throughput is quoted (some brochures give the effective kg/h directly).
    """
    power_kw, power_raw = parse.power(text)
    if not power_kw:
        return None
    cycle = _first(mi.CYCLE_TIME_PATTERN, text)
    batch = _first(mi.BATCH_KG_PATTERN, text)
    if cycle and batch:
        cycle_h = _to_hours(float(cycle["value"]), cycle["unit"])
        batch_kg = float(batch["value"])
        if batch_kg > 0 and cycle_h > 0:
            kwh = round(power_kw * cycle_h / batch_kg, 4)
            basis = (
                f"{power_raw} × {cycle['raw']} ÷ {batch['raw']} = "
                f"{power_kw} kW × {cycle_h} h ÷ {batch_kg} kg = {kwh} kWh/kg fabric"
            )
            return Result(
                kwh_per_unit=kwh,
                unit="kWh/kg fabric",
                installed_power_kw=power_kw,
                throughput_kg_per_h=None,
                basis=basis,
                confidence=0.7,  # batch×cycle is solid but assumes full-batch utilization
                rule_name="batch-cycle",
            )
    # Degrade to mass-rate if the brochure gives an effective kg/h.
    return rule_mass_rate(text, parse)


def rule_per_garment(text: str, parse: _Parse) -> Optional[Result]:
    """Per-garment machines (Lockstitch/Sewing, Embroidery, Trims Attachment):
    when the brochure quotes stitches/min (or pcs/min), a coarse per-garment
    proxy is ``kW ÷ (rate × 60)`` -> ``kWh/garment-eq``. Falls back to mass-rate
    when a kg/h throughput is present, else None (power-only evidence)."""
    power_kw, power_raw = parse.power(text)
    if not power_kw:
        return None
    throughput_kg_per_h, _throughput_raw = parse.throughput_kg_per_h(text)
    if throughput_kg_per_h and throughput_kg_per_h > 0:
        # An effective kg/h on a garment machine is still usable as mass-rate.
        return rule_mass_rate(text, parse)
    normalised = " ".join(text.split())
    for match in mi.THROUGHPUT_PATTERN.finditer(normalised):
        unit = match.group("unit").lower()
        if unit.startswith(("stitches", "pcs", "rpm", "sti")):
            rate = mi._num(match.group("value"))
            if rate > 0:
                # kWh per stitch-minute-rate — a coarse per-garment proxy.
                kwh = round(power_kw / (rate * 60.0), 6)
                basis = (
                    f"{power_raw} ÷ ({match.group(0)} × 60) = {power_kw} kW "
                    f"÷ {rate * 60} stitch-equiv/h = {kwh} kWh/garment-eq"
                )
                return Result(
                    kwh_per_unit=kwh,
                    unit="kWh/garment",
                    installed_power_kw=power_kw,
                    throughput_kg_per_h=None,
                    basis=basis,
                    confidence=0.55,
                    rule_name="per-garment",
                )
    return None


def rule_feed_area(text: str, parse: _Parse) -> Optional[Result]:
    """Cutting/Spreading (Straight-Knife / CNC, spreading): installed power over
    (cut_speed × fabric_width × 3600) -> ``kWh/m²``. Falls back to mass-rate."""
    power_kw, power_raw = parse.power(text)
    if not power_kw:
        return None
    speed = _first(mi.LINEAR_SPEED_PATTERN, text)
    width = _first(mi.WIDTH_PATTERN, text)
    if speed and width:
        # LINEAR_SPEED is m/min; convert to m²/h (×60 -> m²/h for the kW / (m²/h) shape).
        spd_m_per_min = _to_meters(float(speed["value"]), speed["unit"])
        width_m = _to_meters(float(width["value"]), width["unit"])
        # m/min already; if the regex unit was m/s, treat as m/min — rare on brochures.
        if speed["unit"].lower().endswith("/s"):
            spd_m_per_min *= 60.0
        m2_per_h = spd_m_per_min * width_m * 60.0
        if m2_per_h > 0:
            kwh = round(power_kw / m2_per_h, 6)  # kW / (m²/h) = kWh/m²
            basis = (
                f"{power_raw} ÷ ({speed['raw']} × {width['raw']} × 60) = "
                f"{power_kw} kW ÷ {m2_per_h:.2f} m²/h = {kwh} kWh/m²"
            )
            return Result(
                kwh_per_unit=kwh,
                unit="kWh/m²",
                installed_power_kw=power_kw,
                throughput_kg_per_h=None,
                basis=basis,
                confidence=0.6,
                rule_name="feed-area",
            )
    return rule_mass_rate(text, parse)


def rule_area_throughput(text: str, parse: _Parse) -> Optional[Result]:
    """Printing/Coating: ``kW ÷ (m²/h)`` -> ``kWh/m²``. Falls back to mass-rate."""
    power_kw, power_raw = parse.power(text)
    if not power_kw:
        return None
    area = _first(mi.AREA_THROUGHPUT_PATTERN, text)
    if area:
        m2_per_h = float(area["value"])
        if m2_per_h > 0:
            kwh = round(power_kw / m2_per_h, 6)
            basis = f"{power_raw} ÷ {area['raw']} = {power_kw} kW ÷ {m2_per_h} m²/h = {kwh} kWh/m²"
            return Result(
                kwh_per_unit=kwh,
                unit="kWh/m²",
                installed_power_kw=power_kw,
                throughput_kg_per_h=None,
                basis=basis,
                confidence=0.75,
                rule_name="area-throughput",
            )
    return rule_mass_rate(text, parse)


def rule_thermal(text: str, parse: _Parse) -> Optional[Result]:
    """Stenter/Ironing/Drying/Finishing: thermal machines are often quoted as
    throughput kg/h (evaporation rate) so mass-rate applies; when only an area
    throughput (m²/h) is given, prefer that and re-tag unit for fabric. Falls
    back to mass-rate."""
    power_kw, _ = parse.power(text)
    if not power_kw:
        return None
    area = rule_area_throughput(text, parse)
    if area is not None and area.rule_name == "area-throughput":
        return Result(
            kwh_per_unit=area.kwh_per_unit,
            unit="kWh/kg fabric",
            installed_power_kw=area.installed_power_kw,
            throughput_kg_per_h=None,
            basis=area.basis,
            confidence=0.65,
            rule_name="thermal",
        )
    return rule_mass_rate(text, parse)


def rule_unknown(text: str, parse: _Parse) -> Optional[Result]:
    """Best-effort for categories without a dedicated rule: try mass-rate, then
    mark power-only low-conf. Never silently proxy, never raise. Phase 4 will
    queue these; here we just flag low confidence so the step's process fallback
    still guards carbon."""
    rate = rule_mass_rate(text, parse)
    if rate is not None:
        # Demote confidence: mass-rate on an unknown rule is a guess.
        return Result(
            kwh_per_unit=rate.kwh_per_unit,
            unit=rate.unit,
            installed_power_kw=rate.installed_power_kw,
            throughput_kg_per_h=rate.throughput_kg_per_h,
            basis=rate.basis,
            confidence=0.35,
            rule_name="unknown-best-effort",
        )
    power_kw, power_raw = parse.power(text)
    if power_kw:
        return Result(
            kwh_per_unit=0.0,
            unit="kWh/kg",
            installed_power_kw=power_kw,
            throughput_kg_per_h=None,
            basis=f"{power_raw} found; no throughput -> unsupported (power-only evidence, needs rule)",
            confidence=0.2,
            rule_name="unknown-power-only",
        )
    return None


# ---------------------------------------------------------------------------
# Registry + dispatcher
# ---------------------------------------------------------------------------


# Category keys are the master's specific category names
# (machine_models.csv machine_category col). Aliases map the broader
# machine_recommender categories (Sewing, Cutting, Printing, ...) onto a rule.
_DERIVATION_RULES: dict[str, Rule] = {
    "Ring Frame": rule_mass_rate,
    "Circular Knitting Machine": rule_mass_rate,
    "Jet Dyeing Machine": rule_batch_cycle,
    "Washing Machine": rule_batch_cycle,
    "Lockstitch Machine": rule_per_garment,
    "CNC Fabric Cutter": rule_feed_area,
    "Straight Knife Cutter": rule_feed_area,
    "Spreading Machine": rule_feed_area,
    "Printing Machine": rule_area_throughput,
    "Stenter Machine": rule_thermal,
    "Ironing Machine": rule_thermal,
    "Drying Machine": rule_thermal,
}

# Broader catalog categories -> a master category with a rule. The
# machine_recommender uses short names; this routes them to the right physics.
# Empty string => non-energy category (Design/Quality/Inspection) -> unknown rule.
_CATEGORY_ALIASES: dict[str, str] = {
    "Sewing": "Lockstitch Machine",
    "Cutting": "CNC Fabric Cutter",
    "Spreading": "Spreading Machine",
    "Printing": "Printing Machine",
    "Ironing": "Ironing Machine",
    "Drying": "Drying Machine",
    "Finishing": "Stenter Machine",
    "Pre-treatment": "Jet Dyeing Machine",
    "Washing": "Washing Machine",
    "Embroidery": "Lockstitch Machine",
    "Trims Attachment": "Lockstitch Machine",
    "Trimming": "Lockstitch Machine",
    "Packaging": "Ring Frame",  # mass-rate proxy; no dedicated rule yet
    "Design": "",
    "Quality": "",
    "Inspection": "",
}


def _resolve_rule(category: str) -> Rule:
    category = (category or "").strip()
    if not category:
        return rule_unknown
    if category in _DERIVATION_RULES:
        return _DERIVATION_RULES[category]
    alias = _CATEGORY_ALIASES.get(category)
    if alias and alias in _DERIVATION_RULES:
        return _DERIVATION_RULES[alias]
    return rule_unknown


def derive_for_category(category: str, text: str, parse: _Parse) -> Optional[Result]:
    """Dispatch to the category's rule. Returns a :class:`Result` or None when
    no usable figure is present at all. Never raises — a regex/parse hiccup
    must never abort discovery."""
    try:
        return _resolve_rule(category)(text, parse)
    except Exception:
        return rule_unknown(text, parse)


def has_category_rule(category: str) -> bool:
    """True if ``category`` (or its alias) has a *dedicated* derivation rule,
    i.e. it resolves to anything but :func:`rule_unknown`. Used by the
    coverage sweep to flag unsupported-rule categories for reviewer action."""
    return _resolve_rule(category) is not rule_unknown


__all__ = [
    "Result",
    "Rule",
    "derive_for_category",
    "has_category_rule",
    "rule_mass_rate",
    "rule_batch_cycle",
    "rule_per_garment",
    "rule_feed_area",
    "rule_area_throughput",
    "rule_thermal",
    "rule_unknown",
]
