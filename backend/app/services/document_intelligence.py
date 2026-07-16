from __future__ import annotations

import csv
import io
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterable

# ---------------------------------------------------------------------------
# Signal model
# ---------------------------------------------------------------------------
# A Bill of Materials entry is the primary, accurate input path. Free-text
# description remains a fallback that fills gaps the BOM does not provide.
# Fields set explicitly via the BOM win over regex guesses from prose.


MATERIAL_ALIASES = {
    "organic cotton": "organic cotton",
    "recycled cotton": "recycled cotton",
    "recycled polyester": "recycled polyester",
    "cotton": "cotton",
    "polyester": "polyester",
    "elastane": "elastane",
    "spandex": "elastane",
    "viscose": "viscose",
    "rayon": "viscose",
    "modal": "modal",
    "lyocell": "lyocell",
    "tencel": "lyocell",
    "hemp": "hemp",
    "linen": "linen",
    "nylon": "nylon",
    "polyamide": "nylon",
    "wool": "wool",
    "silk": "silk",
    "leather": "leather",
    "eva": "eva",
    "rubber": "rubber",
}

BLEND_PATTERN = re.compile(
    r"(?P<percent>\d{1,3})\s*%?\s*(?P<material>organic cotton|recycled cotton|recycled polyester|cotton|polyester|elastane|spandex|viscose|modal|lyocell|hemp|nylon|wool|silk|leather)",
    re.IGNORECASE,
)
GSM_PATTERN = re.compile(r"(?P<gsm>\d{2,3})\s*(?:gsm|g/m2|g\/m2)", re.IGNORECASE)
WEIGHT_PATTERN = re.compile(r"(?P<weight>\d{2,5})\s*(?:g|gram|grams|kg)\b", re.IGNORECASE)


@dataclass(frozen=True)
class BOMComponent:
    """One material line of a Bill of Materials."""

    material: str
    percent: float | None
    weight_g: float | None
    origin: str | None


@dataclass
class DocumentSignals:
    """All signals extracted from the user input (BOM + description + uploads).

    Structured fields come from the BOM when provided; the free-text description
    fills whatever the BOM omits. Explicit BOM values always win over regex guesses.
    """

    source_text: str
    product_hint: str | None
    blend: list[dict[str, str | int]]
    gsm: int | None
    weight_g: int | None
    keywords: list[str]
    # Structured BOM (new): primary accurate input path per the brief.
    bom_components: list[BOMComponent] = field(default_factory=list)
    declared_origin: str | None = None
    # How each top-level signal was resolved, for the inference trace.
    provenance: dict[str, str] = field(default_factory=dict)


# ---------------------------------------------------------------------------
# Free-text signal extraction (unchanged behaviour, refactored)
# ---------------------------------------------------------------------------

def _detect_keywords(text: str) -> list[str]:
    keyword_bank = [
        "t-shirt",
        "tee",
        "polo",
        "hoodie",
        "sweatshirt",
        "legging",
        "short",
        "shirt",
        "jeans",
        "denim",
        "chino",
        "dress",
        "jacket",
        "sock",
        "sports bra",
        "sneaker",
        "running shoe",
        "sandal",
        "boot",
        "cotton",
        "polyester",
        "recycled polyester",
        "elastane",
        "viscose",
        "woven",
        "knit",
        "fleece",
        "pique",
        "shell",
    ]
    lowered = text.lower()
    return [keyword for keyword in keyword_bank if keyword in lowered]


def _normalize_material(raw: str) -> str:
    lowered = raw.strip().lower()
    return MATERIAL_ALIASES.get(lowered, lowered)


def _parse_blend_from_text(text: str) -> list[dict[str, str | int]]:
    return [
        {"material": _normalize_material(match.group("material")), "percent": int(match.group("percent"))}
        for match in BLEND_PATTERN.finditer(text)
    ]


# ---------------------------------------------------------------------------
# Structured BOM normalisation
# ---------------------------------------------------------------------------

def _coerce_percent(value: object) -> float | None:
    if value in (None, ""):
        return None
    try:
        text = str(value).strip().rstrip("%").strip()
        return float(text) if text else None
    except (TypeError, ValueError):
        return None


def _coerce_weight_g(value: object) -> float | None:
    if value in (None, ""):
        return None
    try:
        return float(str(value).strip())
    except (TypeError, ValueError):
        return None


def normalize_bom(raw_components: Iterable[dict]) -> tuple[list[BOMComponent], dict[str, str]]:
    """Normalize caller-supplied BOM dicts into BOMComponent records.

    Accepts loose key names (material/material_name/fabric, percent/share,
    weight_g/weight/grams, origin/country) so a hand-typed JSON BOM just works.
    Returns the components plus a small provenance note per material.
    """
    components: list[BOMComponent] = []
    provenance: dict[str, str] = {}
    for index, row in enumerate(raw_components):
        material_name = str(
            row.get("material") or row.get("material_name") or row.get("fabric") or ""
        ).strip()
        if not material_name:
            continue
        material = _normalize_material(material_name)
        percent = _coerce_percent(row.get("percent") or row.get("share") or row.get("percentage"))
        weight_g = _coerce_weight_g(row.get("weight_g") or row.get("weight") or row.get("grams"))
        origin = str(row.get("origin") or row.get("country") or "").strip().lower() or None
        components.append(BOMComponent(material=material, percent=percent, weight_g=weight_g, origin=origin))
        provenance[material] = "BOM"
    return components, provenance


def _blend_from_bom(components: list[BOMComponent]) -> list[dict[str, str | int]]:
    """Convert BOM components into the legacy blend representation used downstream.

    Percent is int (matching the free-text parser); components without a percent
    are still listed so downstream code sees every declared material.
    """
    blend: list[dict[str, str | int]] = []
    for component in components:
        if component.percent is not None:
            blend.append({"material": component.material, "percent": int(round(component.percent))})
        else:
            blend.append({"material": component.material, "percent": 0})
    return blend


def _total_weight_g(components: list[BOMComponent]) -> float | None:
    direct = sum(component.weight_g for component in components if component.weight_g)
    return direct or None


def _primary_origin(components: list[BOMComponent]) -> str | None:
    for component in components:
        if component.origin:
            return component.origin
    return None


# ---------------------------------------------------------------------------
# Uploaded-file parsing (PDF / Excel / CSV / plain text)
# ---------------------------------------------------------------------------
# Libraries are imported lazily so the backend still boots if a parser is
# missing. pdfplumber/pdfminer and openpyxl cover the common tech-pack formats.

def _extract_text_from_pdf(raw: bytes) -> str | None:
    try:
        import pdfplumber  # type: ignore
    except ImportError:
        return None
    try:
        with pdfplumber.open(io.BytesIO(raw)) as pdf:
            pages = []
            for page in pdf.pages:
                pages.append(page.extract_text() or "")
            return "\n".join(pages).strip()
    except Exception:
        return None


def _extract_text_from_excel(raw: bytes) -> str | None:
    try:
        import openpyxl  # type: ignore
    except ImportError:
        return None
    try:
        workbook = openpyxl.load_workbook(io.BytesIO(raw), read_only=True, data_only=True)
        chunks: list[str] = []
        for sheet in workbook.worksheets:
            for row in sheet.iter_rows(values_only=True):
                cells = [str(cell).strip() for cell in row if cell is not None and str(cell).strip()]
                if cells:
                    chunks.append(" | ".join(cells))
        return "\n".join(chunks).strip() if chunks else None
    except Exception:
        return None


def _extract_text_from_csv(raw: bytes) -> str | None:
    try:
        text = raw.decode("utf-8-sig")
    except UnicodeDecodeError:
        return None
    try:
        reader = csv.reader(io.StringIO(text))
        rows = [" | ".join(cell.strip() for cell in row if cell.strip()) for row in reader if any(cell.strip() for cell in row)]
        return "\n".join(rows).strip() if rows else None
    except Exception:
        return None


def _extract_text_from_bytes(uploaded_file) -> str:
    """Extract text from an uploaded file object (FastAPI UploadFile).

    Returns '' when the format is unsupported or parsing fails; the caller treats
    empty text as a no-op. The filename hint is appended so keyword detection can
    still surface a product type even from binary files we cannot parse.
    """
    name = (getattr(uploaded_file, "filename", "") or "").lower()
    try:
        raw = uploaded_file.read()
    except Exception:
        return ""
    finally:
        # Rewind so downstream consumers can still read the bytes if needed.
        try:
            uploaded_file.seek(0)
        except Exception:
            pass

    text: str | None = None
    if name.endswith(".pdf") or raw[:4] == b"%PDF":
        text = _extract_text_from_pdf(raw)
    elif name.endswith((".xlsx", ".xlsm")):
        text = _extract_text_from_excel(raw)
    elif name.endswith(".csv"):
        text = _extract_text_from_csv(raw)
    elif name.endswith((".txt", ".md")) or not raw[:4].strip(b"\x00").isascii():
        try:
            text = raw.decode("utf-8")
        except UnicodeDecodeError:
            text = None

    fallback = f"[uploaded:{name}]" if name else ""
    return f"{text}\n{fallback}".strip() if text else fallback


# ---------------------------------------------------------------------------
# Public entry points
# ---------------------------------------------------------------------------

def extract_text_from_uploads(uploaded_files: list) -> list[str]:
    """Parse each UploadFile into extracted text. Kept for callers that want
    to inspect raw upload content before signal extraction.

    Tolerates a non-iterable default (FastAPI's File() sentinel) so the endpoint
    is safely callable in-process with no files argument.
    """
    if not uploaded_files:
        return []
    try:
        return [_extract_text_from_bytes(uploaded_file) for uploaded_file in uploaded_files]
    except TypeError:
        return []


def extract_document_signals(
    description: str,
    uploaded_texts: list[str],
    *,
    bom_components: Iterable[dict] | None = None,
    declared_origin: str | None = None,
) -> DocumentSignals:
    """Build DocumentSignals from a free-text description, structured BOM, and
    any uploaded tech-pack text. Structured BOM values override regex guesses.
    """
    source_text = "\n".join([description.strip(), *uploaded_texts]).strip()

    bom, bom_provenance = normalize_bom(bom_components or [])
    declared_origin = (declared_origin or "").strip().lower() or None

    # Weight: BOM component weights > BOM-declared nothing > regex on prose.
    text_weight = int(WEIGHT_PATTERN.search(source_text).group("weight")) if WEIGHT_PATTERN.search(source_text) else None
    bom_weight = _total_weight_g(bom)
    weight_g: int | None = None
    weight_source = "description"
    if bom_weight:
        weight_g = int(round(bom_weight))
        weight_source = "BOM"
    elif text_weight:
        weight_g = text_weight
        weight_source = "description"

    # Blend: BOM blend is authoritative; fall back to regex blend from prose.
    text_blend = _parse_blend_from_text(source_text)
    if bom:
        blend = _blend_from_bom(bom)
        blend_source = "BOM"
    else:
        blend = text_blend
        blend_source = "description"

    # GSM only flows from prose today (BOM rarely states fabric weight per area).
    gsm_match = GSM_PATTERN.search(source_text)
    gsm = int(gsm_match.group("gsm")) if gsm_match else None

    keywords = _detect_keywords(source_text)
    product_hint = keywords[0] if keywords else None

    # Origin: explicit declared_origin > first BOM component origin.
    origin = declared_origin or _primary_origin(bom)

    provenance = {
        **bom_provenance,
        "weight_g": weight_source,
        "blend": blend_source,
        "gsm": "description" if gsm else "default",
        "origin": "BOM" if origin and (declared_origin or any(c.origin for c in bom)) else "default",
    }

    return DocumentSignals(
        source_text=source_text,
        product_hint=product_hint,
        blend=blend,
        gsm=gsm,
        weight_g=weight_g,
        keywords=keywords,
        bom_components=bom,
        declared_origin=origin,
        provenance=provenance,
    )
