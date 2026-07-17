"""Step 4: the real brochure -> power -> carbon path for apparel machines.

The KG V2 energy profiles are industry-average proxies ("Pending Validation",
confidence ~0.5). This module turns authentic machine brochure/datasheet text
into *near-exact* energy profiles (kWh per kg of processed material) and lets
those flow through `estimate_resources`, replacing the proxies.

Governance (docs/Machine_Intelligence.md): brochure extraction is *source
evidence*, NOT inference output. Extraction candidates are produced for review;
only an explicit `promote_*` call stamps an approved derivation back into the
`machine_energy_profiles.csv` master. We never auto-write masters from a runtime
extraction. Masters remain the single source of truth.

The core derivation is the physics identity every machine obeys:

    kWh per kg = installed_power_(kW) / throughput_(kg_per_hour)

So a 9 kW cutter that moves 120 kg/h -> 0.075 kWh/kg, and a 75 kW jet dyeing
machine at 250 kg/h -> 0.30 kWh/kg. Each derived value keeps its source raw
text and the candidate power/throughput that produced it, so a reviewer can
trace exactly why the number is what it is.
"""
from __future__ import annotations

import csv
from dataclasses import dataclass
from pathlib import Path

from app.services.knowledge_loader import confidence_level, load_master_data
from app.config import MASTER_DATA_ROOT
from app.services import machine_intelligence as mi

_ENERGY_PROFILES_CSV = MASTER_DATA_ROOT / "machine_energy_profiles.csv"
_MACHINE_BROCHURES_CSV = MASTER_DATA_ROOT / "machine_brochures.csv"

# Target unit per machine category. The energy profile table is keyed per
# machine model, but the *physical* unit is determined by the category
# (jet dyeing is per kg fabric, a lockstitch is per garment, etc.).
_CATEGORY_UNIT = {
    "Jet Dyeing Machine": "kWh/kg fabric",
    "Circular Knitting Machine": "kWh/kg fabric",
    "Ring Frame": "kWh/kg yarn",
    "Lockstitch Machine": "kWh/garment",
    "Stenter Machine": "kWh/kg fabric",
    "CNC Fabric Cutter": "kWh/kg garment",
}


@dataclass(frozen=True)
class ExtractedSpec:
    field_name: str
    raw: str
    value: float
    unit: str


@dataclass
class DerivedProfile:
    machine_model_id: str
    installed_power_kw: float | None
    throughput_kg_per_h: float | None
    derived_kwh_per_unit: float | None
    unit: str
    energy_source: str
    derivation_basis: str  # the raw power + throughput text that fed the number
    confidence: float


def _adapter_for(machine_model_id: str, master_data: dict) -> dict:
    """Return the machine_models row + its current energy profile for context."""
    models = {m["machine_model_id"]: m for m in master_data["datasets"]["machine_models"]}
    return models.get(machine_model_id, {})


def _parse_power(text: str) -> tuple[float | None, str]:
    """Return (kW, raw_text) for the first power figure, converting HP->kW."""
    normalised = " ".join(text.split())
    for match in mi.POWER_PATTERN.finditer(normalised):
        value = float(match.group("value"))
        unit = match.group("unit").lower()
        kw = value if unit.startswith("kw") else value * 0.7457  # hp -> kw
        return kw, match.group(0)
    return None, ""


def _parse_throughput_kg_per_h(text: str) -> tuple[float | None, str]:
    """Return (kg/h, raw_text), taking only mass-rate throughput as derivation-grade."""
    normalised = " ".join(text.split())
    for match in mi.THROUGHPUT_PATTERN.finditer(normalised):
        unit = match.group("unit").lower()
        if unit.startswith("kg"):  # kg/h, kg/hr, kg/hour, kg per hour
            return float(match.group("value")), match.group(0)
    return None, ""


def extract_brochure(machine_model_id: str, text: str, source: str = "brochure_text") -> dict:
    """Extract candidate specs + DERIVE a kWh-per-unit energy profile from brochure text.

    Returns the review candidate plus its derivation; does NOT write anywhere.
    The caller (or a reviewer) decides whether to `promote_energy_profile`.
    """
    from app.services.machine_intelligence import extract_machine_specs

    candidates = extract_machine_specs(text, machine_model_id, source)
    power_kw, power_raw = _parse_power(text)
    throughput_kg_per_h, throughput_raw = _parse_throughput_kg_per_h(text)

    derived_kwh_per_unit = None
    derivation_basis = ""
    confidence = 0.35
    if power_kw and throughput_kg_per_h and throughput_kg_per_h > 0:
        derived_kwh_per_unit = round(power_kw / throughput_kg_per_h, 4)
        derivation_basis = f"{power_raw} / {throughput_raw} = {power_kw} kW / {throughput_kg_per_h} kg/h"
        # A derivation from BOTH real power and real throughput is the gold path;
        # power-only (no throughput) is unusable for a per-unit energy number.
        confidence = 0.8
    elif power_kw:
        derivation_basis = f"{power_raw} found but no kg/h throughput -> no per-unit derivation possible"
        confidence = 0.45

    unit = _CATEGORY_UNIT.get(
        (_adapter_for(machine_model_id, load_master_data()) or {}).get("machine_category", ""),
        "kWh/kg",
    )

    return {
        "machine_model_id": machine_model_id,
        "source": source,
        "candidate_specs": candidates["extracted_fields"],
        "derivation": {
            "installed_power_kw": power_kw,
            "throughput_kg_per_h": throughput_kg_per_h,
            "derived_kwh_per_unit": derived_kwh_per_unit,
            "unit": unit,
            "derivation_basis": derivation_basis,
            "confidence": confidence_level(confidence),
        },
        "current_profile": (load_master_data()["machine_energy_by_model"]).get(machine_model_id, {}),
        "storage_policy": "Candidate only. Call promote_energy_profile to write an approved derivation into machine_energy_profiles.csv.",
    }


def promote_energy_profile(machine_model_id: str, derived_kwh_per_unit: float, *, unit: str, source: str) -> dict:
    """Stamp an approved brochure-derived profile into machine_energy_profiles.csv.

    This is the only function that writes the masters in Step 4, and only on an
    explicit, reviewed call (governance: never auto-write masters from a runtime
    extraction). The overwritten row keeps `approval_status = Brochure Approved`
    and a raised confidence so it visibly supersedes the KG-proxy it replaces.
    """
    rows = []
    fieldnames: list[str] = []
    replaced = False
    with _ENERGY_PROFILES_CSV.open(newline="", encoding="utf-8") as handle:
        reader = csv.DictReader(handle)
        fieldnames = list(reader.fieldnames or [])
        for row in reader:
            if row["machine_model_id"] == machine_model_id:
                row["electricity"] = str(derived_kwh_per_unit)
                row["unit"] = unit or row.get("unit", "kWh/kg")
                row["source"] = f"Brochure-derived: {source}"
                row["approval_status"] = "Brochure Approved"
                row["confidence"] = "0.8"
                row["version"] = "1.1"
                replaced = True
            rows.append(row)

    if not replaced:
        # Append a new profile row if the model had none.
        rows.append(
            {
                "machine_model_id": machine_model_id,
                "unit": unit or "kWh/kg",
                "electricity": str(derived_kwh_per_unit),
                "steam": "0",
                "water": "",
                "compressed_air": "",
                "natural_gas": "",
                "source": f"Brochure-derived: {source}",
                "version": "1.1",
                "effective_date": "",
                "expiry_date": "",
                "approval_status": "Brochure Approved",
                "confidence": "0.8",
            }
        )

    with _ENERGY_PROFILES_CSV.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames or list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(rows)

    # Invalidate the cached master data so estimate_resources picks up the new value.
    load_master_data.cache_clear()

    return {
        "machine_model_id": machine_model_id,
        "electricity": derived_kwh_per_unit,
        "unit": unit or "kWh/kg",
        "source": f"Brochure-derived: {source}",
        "approval_status": "Brochure Approved",
        "confidence": 0.8,
        "written_to": str(_ENERGY_PROFILES_CSV),
    }


def persist_brochure_observations(
    machine_model_id: str,
    *,
    brochure_id: str | None,
    url: str,
    installed_power_kw: float,
    throughput_kg_per_h: float,
) -> dict[str, object]:
    """Stamp a live-derived power/throughput back into machine_brochures.csv.

    Unlike ``promote_energy_profile`` (reviewer-only, writes the energy master),
    this records the *raw brochure observation* the live discovery just made, so
    the next run benefits from the now-known brochure URL (Tier 0.5 reads it back
    without re-fetching) and a reviewer sees the derivation basis.

    Governance: writes ONLY when a real derivation succeeded (both figures
    truthy). Never writes TBD/partial figures, never fabricates. ``observed_capacity``
    stores an ``"N kg/h"`` string. Clears the ``load_master_data`` lru_cache so the
    next read sees the update. Mirrors ``promote_energy_profile``'s read/mutate/
    rewrite pattern.
    """
    if not installed_power_kw or not throughput_kg_per_h:
        return {"machine_model_id": machine_model_id, "written": False,
                "reason": "no complete derivation (power + throughput required)"}
    if not (url or "").lower().startswith(("http://", "https://")):
        return {"machine_model_id": machine_model_id, "written": False,
                "reason": "no authentic source URL"}

    rows: list[dict[str, str]] = []
    fieldnames: list[str] = []
    found = False
    with _MACHINE_BROCHURES_CSV.open(newline="", encoding="utf-8") as handle:
        reader = csv.DictReader(handle)
        fieldnames = list(reader.fieldnames or [])
        for row in reader:
            row_id = row.get("brochure_id", "")
            row_model = row.get("machine_model_id", "")
            matches = (brochure_id and row_id == brochure_id) or (row_model == machine_model_id)
            if matches and not found:
                row["public_url"] = url
                row["observed_power_kw"] = f"{installed_power_kw:g}"
                row["observed_capacity"] = f"{throughput_kg_per_h:g} kg/h"
                row["extraction_status"] = "Live-derived"
                row["source"] = f"Brochure-derived live: {installed_power_kw:g} kW / {throughput_kg_per_h:g} kg/h"
                row["approval_status"] = row.get("approval_status") or "Pending Brochure Review"
                row["source_status"] = row.get("source_status") or "Public URL resolved"
                found = True
            rows.append(row)

    if not found:
        return {"machine_model_id": machine_model_id, "written": False,
                "reason": "no machine_brochures.csv row for this model/brochure_id"}

    with _MACHINE_BROCHURES_CSV.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames or list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(rows)

    load_master_data.cache_clear()

    return {
        "machine_model_id": machine_model_id,
        "brochure_id": brochure_id,
        "public_url": url,
        "observed_power_kw": installed_power_kw,
        "observed_capacity": f"{throughput_kg_per_h:g} kg/h",
        "written": True,
        "written_to": str(_MACHINE_BROCHURES_CSV),
    }


def brochure_review_summary() -> list[dict]:
    """For each machine model: its current (proxy) energy profile vs. what a
    brochure derivation would replace it with. Drives the review workbench."""
    master = load_master_data()
    out: list[dict] = []
    for model in master["datasets"]["machine_models"]:
        model_id = model["machine_model_id"]
        current = master["machine_energy_by_model"].get(model_id, {})
        out.append(
            {
                "machine_model_id": model_id,
                "manufacturer": model["manufacturer"],
                "model": model["model"],
                "machine_category": model["machine_category"],
                "current_electricity": current.get("electricity", ""),
                "current_unit": current.get("unit", ""),
                "current_source": current.get("source", ""),
                "current_approval": current.get("approval_status", ""),
                "current_confidence": current.get("confidence", ""),
            }
        )
    return out


def fetch_brochure_text(url: str, *, timeout: float = 30.0) -> dict:
    """Download a brochure/datasheet URL and extract its text.

    Uses stdlib urllib (no extra dep). PDFs are decoded via the same pdfplumber
    path as BOM/POM uploads; plain text is decoded as utf-8. Returns a record
    with the extracted text and the bytes fetched so callers can store/audit.
    This is the bridge from "a public URL" to "machine-readable brochure text"
    that extract_brochure then turns into a derivation.
    """
    import urllib.request
    from app.services.document_intelligence import _extract_text_from_pdf

    class _Bytes:
        def __init__(self, raw: bytes):
            self._raw = raw

        def read(self):
            return self._raw

        def seek(self, *_):
            pass

    try:
        with urllib.request.urlopen(url, timeout=timeout) as response:  # noqa: S310 - reviewed at call site
            raw = response.read()
    except Exception as exc:  # broad: network errors are non-fatal here
        return {"url": url, "text": "", "bytes": 0, "error": str(exc)}

    guessed = "pdf" if raw[:4] == b"%PDF" else "text"
    text: str | None
    if guessed == "pdf":
        text = _extract_text_from_pdf(raw)
    else:
        try:
            text = raw.decode("utf-8")
        except UnicodeDecodeError:
            text = None
    return {"url": url, "text": text or "", "bytes": len(raw), "format": guessed}
