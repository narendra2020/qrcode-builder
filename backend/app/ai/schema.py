"""
Prompt and strict JSON schema for analysing one menu / catalogue page.

One call per page returns the category evidence, verbatim business
details and the structured items, so category detection and catalogue
extraction share a single AI pass per image.
"""
from app.catalog.registry import CATEGORIES, ITEM_LABELS

PROMPT_VERSION = "qr-v1"

_NULLABLE_STR = {"type": ["string", "null"]}
_NULLABLE_NUM = {"type": ["number", "null"]}


def _obj(properties: dict) -> dict:
    return {"type": "object", "properties": properties, "required": list(properties), "additionalProperties": False}


PAGE_SCHEMA = _obj({
    "readable": {"type": "boolean"},
    "unreadable_reason": _NULLABLE_STR,
    "category": _obj({
        "insufficient_evidence": {"type": "boolean"},
        "clarifying_question": _NULLABLE_STR,
        "scores": {
            "type": "array",
            "items": _obj({
                "key": {"type": "string", "enum": [c.key for c in CATEGORIES]},
                "confidence": {"type": "number"},
            }),
        },
        "evidence": _NULLABLE_STR,
    }),
    "business": _obj({
        "name": _NULLABLE_STR,
        "phone": _NULLABLE_STR,
        "whatsapp": _NULLABLE_STR,
        "email": _NULLABLE_STR,
        "address": _NULLABLE_STR,
        "opening_hours": _NULLABLE_STR,
        "tagline": _NULLABLE_STR,
    }),
    "currency": _NULLABLE_STR,
    "items": {
        "type": "array",
        "items": _obj({
            "name": {"type": "string"},
            "section": _NULLABLE_STR,
            "description": _NULLABLE_STR,
            "price_raw": _NULLABLE_STR,
            "price": _NULLABLE_NUM,
            "variants": {
                "type": "array",
                "items": _obj({"name": {"type": "string"}, "price_raw": _NULLABLE_STR, "price": _NULLABLE_NUM}),
            },
            "labels": {"type": "array", "items": {"type": "string", "enum": list(ITEM_LABELS)}},
            "name_confidence": {"type": "number"},
            "price_confidence": {"type": "number"},
            "unclear": _NULLABLE_STR,
            "image_box": {"type": ["array", "null"], "items": {"type": "integer"}},
        }),
    },
})


def system_prompt() -> str:
    category_lines = "\n".join(f"- {c.key}: {c.label} — cues: {c.ai_hints}" for c in CATEGORIES)
    label_lines = ", ".join(ITEM_LABELS)
    return f"""You digitise photos of menus, price lists and product catalogues for small Indian businesses so they can publish an online store. Accuracy matters more than completeness: the owner reviews your output, and customers will see prices you transcribe, so a wrong price or invented item does real harm while a gap is easy to fill.

Transcribe only what is visibly printed or written in the image.
- Never invent items, prices, descriptions, ingredients, specifications, addresses or phone numbers. If something is not in the image, return null or an empty list.
- Keep item names and descriptions in the language and script used in the image (menus often mix English with Hindi or another Indian language; keep both as printed). Fix nothing but obvious OCR noise.
- Read multi-column layouts column by column; section headings become each item's `section`.
- `price_raw` is the price text exactly as printed (e.g. "₹ 250/-", "180 / 320", "MRP 1,499"). `price` is the single numeric price only when exactly one unambiguous amount applies to the item; otherwise null. Never compute, convert or guess prices.
- If an item has size/portion/option prices (Half/Full, S/M/L, 250 g/500 g, Regular/Large), put each in `variants` with its own price and leave `price` null unless a separate base price is printed.
- `labels` only for markers explicitly shown for that item (veg/non-veg symbols, "Jain", "spicy" chilli icons, "bestseller"). Allowed: {label_lines}. Do not infer veg/non-veg from the dish name.
- `name_confidence` / `price_confidence` (0 to 1) reflect how legible that text is in the image; use below 0.7 when blurry, cut off, handwritten-ambiguous or overlapping. Describe what is uncertain in `unclear`, otherwise null. Use price_confidence 1 when no price is printed.
- `image_box`: only when the item has its own product photo printed in the catalogue, give [x0, y0, x1, y1] for that photo in a 0-1000 coordinate grid of the full image; otherwise null. Never box decorative art, logos or text.
- `business`: copy the business name, phones, email, address, hours and tagline exactly as printed; null for anything not shown. Do not complete partial addresses.
- `currency`: ISO code only if the currency is shown or the ₹ / Rs symbol is used (INR); otherwise null.

Category: score how well the page fits each business type (only types with real evidence; confidences 0 to 1). Set `insufficient_evidence` true when the image does not show enough to tell, with a short `clarifying_question` for the owner. Put a one-sentence summary of the visible cues in `evidence`.
{category_lines}

If the image is not a menu/catalogue/price list or cannot be read at all, set `readable` false with a short `unreadable_reason` and return no items."""


USER_INSTRUCTION = "Analyse this page and return the JSON described in your instructions."
