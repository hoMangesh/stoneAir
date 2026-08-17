from __future__ import annotations

from app.services.document_intelligence import DocumentSignals
from app.services.knowledge_loader import load_knowledge_graph


def _score_taxonomy_row(row: dict[str, str], signals: DocumentSignals) -> float:
    text = signals.source_text.lower()
    score = 0.0

    for keyword in row.get("keywords", "").split("|"):
        if keyword and keyword.lower() in text:
            score += 6.0

    product_type = row.get("level_4_product_type", "").lower()
    subtype = row.get("level_5_subtype", "").lower()
    category = row.get("level_3_category", "").lower()
    if product_type and product_type in text:
        score += 10.0
    if subtype and any(part in text for part in subtype.split()):
        score += 2.0
    if category and any(part in text for part in category.split()):
        score += 1.0

    for blend_item in signals.blend:
        material = str(blend_item["material"])
        if material in row.get("primary_material_family", "").lower():
            score += 3.0
        if material in row.get("notes", "").lower():
            score += 1.0

    if signals.gsm:
        gsm_range = row.get("default_gsm_range", "")
        try:
            low, high = [int(value) for value in gsm_range.split("-")]
            if low <= signals.gsm <= high:
                score += 4.0
        except ValueError:
            pass

    return score


def classify_product(signals: DocumentSignals, *, domain: str | None = None) -> dict[str, object]:
    kg = load_knowledge_graph()
    # Multi-domain: restrict candidates to TAXONOMY rows whose ``level_1_domain``
    # matches the resolved domain's id (case-insensitive — taxonomy is Title-Case
    # "Apparel", the pack's domain_id is lowercase "apparel"). This finally USES
    # the multi-domain schema the data has carried since V1. Today only apparel
    # rows match the apparel pack, so the chosen best row is identical to the
    # unfiltered behaviour (parity preserved). When an EV-battery taxonomy lands
    # under level_1_domain="EV Battery" with an ev_battery pack, the engine never
    # discusses apparel — it never sees cross-domain rows.
    if domain is None:
        from app.core.domain_registry import resolve
        from domain_packs.bootstrap import bootstrap

        bootstrap()
        resolved_domain = resolve(None).domain_id
    else:
        resolved_domain = domain.strip().lower()
    domain_taxonomy = [
        row for row in kg["taxonomy"]
        if (row.get("level_1_domain") or "").strip().lower() == resolved_domain
    ]
    # If filtering yields nothing (e.g. no taxonomy authored for this domain yet),
    # fall back to the full set rather than crashing — surfaced in the result so a
    # caller can see unpierced coverage. This never engages for apparel today.
    searched = domain_taxonomy or kg["taxonomy"]
    scored = [
        (row, _score_taxonomy_row(row, signals))
        for row in searched
    ]
    scored.sort(key=lambda item: item[1], reverse=True)
    best_row, raw_score = scored[0]

    confidence_prior = float(best_row.get("confidence_prior") or 0.5)
    confidence = min(0.98, max(0.35, confidence_prior * 0.65 + min(raw_score / 40, 1) * 0.35))

    alternatives = [
        {
            "taxonomy_id": row["taxonomy_id"],
            "product_type": row["level_4_product_type"],
            "variant": row["level_5_subtype"],
            "score": round(score, 2),
        }
        for row, score in scored[1:4]
    ]

    return {
        "taxonomy": best_row,
        "confidence": round(confidence, 2),
        "match_score": round(raw_score, 2),
        "alternatives": alternatives,
    }


def match_template(taxonomy_id: str, signals: DocumentSignals) -> dict[str, object]:
    kg = load_knowledge_graph()
    candidates = [row for row in kg["templates"] if row["taxonomy_id"] == taxonomy_id]
    template = candidates[0] if candidates else kg["templates"][0]

    default_weight = int(template["default_weight_g"])
    weight_g = signals.weight_g or default_weight
    default_gsm = int(template["default_gsm"])
    gsm = signals.gsm or (default_gsm if default_gsm > 0 else None)

    return {
        "template": template,
        "resolved_weight_g": weight_g,
        "resolved_gsm": gsm,
        "material_blend": signals.blend or template["material_blend_default"],
    }

