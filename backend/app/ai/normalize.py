"""
Turns raw per-page AI output into validated, review-flagged data.

Defensive by design: anything the model returns is re-checked here. A
numeric `price` that isn't literally present in the printed `price_raw`
is discarded (never trust a computed/hallucinated number), low-confidence
fields are flagged for owner review, and category scores are aggregated
across pages with an explicit low-confidence path.
"""
import re
from decimal import Decimal, InvalidOperation

from app.catalog.registry import CATEGORY_BY_KEY, ITEM_LABELS
from app.core.config import settings

_NUM_RE = re.compile(r"\d[\d,]*(?:\.\d{1,2})?")


def _clean(value, max_len: int) -> str | None:
    if not isinstance(value, str):
        return None
    value = " ".join(value.split())
    return value[:max_len] if value else None


def _conf(value) -> float:
    try:
        return max(0.0, min(1.0, float(value)))
    except (TypeError, ValueError):
        return 0.0


def _numbers_in(text: str | None) -> list[Decimal]:
    out = []
    for match in _NUM_RE.findall(text or ""):
        try:
            out.append(Decimal(match.replace(",", "")))
        except InvalidOperation:
            continue
    return out


def verified_price(price, price_raw: str | None) -> Decimal | None:
    """Accept the model's numeric price only if it appears verbatim in the
    printed price text and is the only amount there."""
    if price is None or isinstance(price, bool):
        return None
    try:
        value = Decimal(str(price)).quantize(Decimal("0.01"))
    except (InvalidOperation, ValueError):
        return None
    if value <= 0 or value >= Decimal("10000000000"):
        return None
    numbers = _numbers_in(price_raw)
    if len(numbers) != 1 or numbers[0] != value:
        return None
    return value


def normalize_item(raw: dict, currency_hint: str | None) -> dict | None:
    name = _clean(raw.get("name"), 160)
    if not name:
        return None
    price_raw = _clean(raw.get("price_raw"), 60)
    price = verified_price(raw.get("price"), price_raw)
    threshold = settings.AI_FIELD_CONFIDENCE_THRESHOLD
    name_conf, price_conf = _conf(raw.get("name_confidence")), _conf(raw.get("price_confidence"))

    variants = []
    for v in raw.get("variants") or []:
        v_name = _clean(v.get("name"), 60)
        if not v_name:
            continue
        v_raw = _clean(v.get("price_raw"), 40)
        v_price = verified_price(v.get("price"), v_raw)
        variants.append({"name": v_name, "price": str(v_price) if v_price is not None else None, "price_text": v_raw})
    variants = variants[:12]

    reasons: list[str] = []
    if name_conf < threshold:
        reasons.append("name_unclear")
    if price_raw and price is None and not variants:
        reasons.append("price_unclear")
    elif price_raw and price_conf < threshold:
        reasons.append("price_low_confidence")
    if any(v["price_text"] and v["price"] is None for v in variants):
        reasons.append("variant_price_unclear")
    unclear = _clean(raw.get("unclear"), 200)
    if unclear and not reasons:
        reasons.append("flagged_by_ai")

    labels = [lbl for lbl in (raw.get("labels") or []) if lbl in ITEM_LABELS]
    box = raw.get("image_box")
    if not (isinstance(box, list) and len(box) == 4 and all(isinstance(n, int) for n in box)):
        box = None

    return {
        "name": name,
        "section": _clean(raw.get("section"), 80),
        "description": _clean(raw.get("description"), 1000),
        "price": price,
        "price_text": None if price is not None else price_raw,
        "variants": variants,
        "labels": sorted(set(labels)),
        "needs_review": bool(reasons),
        "review_reasons": reasons,
        "confidence": {"name": name_conf, "price": price_conf, "note": unclear},
        "image_box": box,
    }


def aggregate_category(pages: list[dict]) -> dict:
    """Weighted mean of per-page category scores (weight = item count + 1)."""
    totals: dict[str, float] = {}
    weight_sum = 0.0
    questions: list[str] = []
    evidence: list[str] = []
    insufficient_pages = 0
    for page in pages:
        cat = page.get("category") or {}
        if cat.get("insufficient_evidence"):
            insufficient_pages += 1
            if cat.get("clarifying_question"):
                questions.append(_clean(cat["clarifying_question"], 200))
        if cat.get("evidence"):
            evidence.append(_clean(cat["evidence"], 300))
        weight = len(page.get("items") or []) + 1
        weight_sum += weight
        for score in cat.get("scores") or []:
            key = score.get("key")
            if key in CATEGORY_BY_KEY:
                totals[key] = totals.get(key, 0.0) + _conf(score.get("confidence")) * weight

    ranked = sorted(
        ({"key": k, "confidence": round(v / weight_sum, 3)} for k, v in totals.items() if weight_sum),
        key=lambda s: s["confidence"], reverse=True,
    )
    top = ranked[0] if ranked else None
    insufficient = not top or insufficient_pages == len(pages)
    low = insufficient or top["confidence"] < settings.AI_CATEGORY_CONFIDENCE_THRESHOLD
    return {
        "suggested": None if insufficient else top["key"],
        "confidence": top["confidence"] if top else 0.0,
        "low_confidence": low,
        "insufficient_evidence": insufficient,
        "alternatives": [s for s in ranked[1:4] if s["confidence"] > 0.05] if top else [],
        "clarifying_question": next((q for q in questions if q), None) if low else None,
        "evidence": evidence[0] if evidence else None,
    }


_BUSINESS_FIELDS = {"name": 120, "phone": 40, "whatsapp": 40, "email": 255, "address": 255, "opening_hours": 300, "tagline": 160}


def aggregate_business(pages: list[dict]) -> dict:
    """First non-empty verbatim value per field across pages."""
    out: dict[str, str | None] = {k: None for k in _BUSINESS_FIELDS}
    for page in pages:
        biz = page.get("business") or {}
        for key, max_len in _BUSINESS_FIELDS.items():
            if out[key] is None:
                out[key] = _clean(biz.get(key), max_len)
    return out


def aggregate_currency(pages: list[dict]) -> str | None:
    for page in pages:
        cur = (page.get("currency") or "").strip().upper()
        if re.fullmatch(r"[A-Z]{3}", cur):
            return cur
    return None
