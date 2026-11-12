"""
Catalogue (categories + items) reads, the single bulk-save operation, and
importing AI extraction results.

All catalogue writes go through save_catalogue(): one transaction that
locks the store row, checks the optimistic version, diffs the submitted
catalogue against the stored one, enforces the monthly quota (see
app/services/plans.py) only when something actually changed on a
published store, writes a revision row and bumps catalogue_version.
"""
import hashlib
import io
import json
from decimal import Decimal, InvalidOperation

from fastapi import HTTPException, status
from PIL import Image
from sqlalchemy.orm import Session

from app.catalog.registry import ITEM_LABELS
from app.core.config import settings
from app.models.models import (
    CatalogueCategory,
    CatalogueItem,
    CatalogueRevision,
    ExtractionJob,
    JobStatusEnum,
    Media,
    MediaKindEnum,
    Store,
    User,
)
from app.services import media as media_service
from app.services import plans
from app.services.audit import audit

MAX_PRICE = Decimal("9999999999.99")


class CatalogueValidationError(ValueError):
    def __init__(self, errors: list[dict]):
        super().__init__("Catalogue has errors")
        self.errors = errors


# ---------------------------------------------------------------- reads ----

def catalogue_out(store: Store, db: Session) -> dict:
    media_ids = [i.image_media_id for i in store.items if i.image_media_id]
    media = {m.id: m for m in db.query(Media).filter(Media.id.in_(media_ids)).all()} if media_ids else {}
    return {
        "version": store.catalogue_version,
        "currency": store.currency,
        "categories": [{"id": c.id, "name": c.name} for c in store.categories],
        "items": [
            {
                "id": i.id,
                "category_id": i.category_id,
                "name": i.name,
                "description": i.description,
                "price": str(i.price) if i.price is not None else None,
                "price_text": i.price_text,
                "variants": i.variants,
                "labels": i.labels,
                "available": i.available,
                "image": media_service.media_out(media.get(i.image_media_id)) if i.image_media_id else None,
                "source": i.source,
                "needs_review": i.needs_review,
                "review_reasons": i.review_reasons,
                "confidence": i.confidence,
            }
            for i in store.items
        ],
        "review_count": sum(1 for i in store.items if i.needs_review),
    }


# ----------------------------------------------------------- validation ----

def _str(value, field: str, max_len: int, errors: list, where: str, required: bool = False) -> str | None:
    if value is None or (isinstance(value, str) and not value.strip()):
        if required:
            errors.append({"where": where, "field": field, "message": "This is required."})
        return None
    if not isinstance(value, str):
        errors.append({"where": where, "field": field, "message": "Must be text."})
        return None
    value = value.strip()
    if len(value) > max_len:
        errors.append({"where": where, "field": field, "message": f"Must be at most {max_len} characters."})
        return None
    return value


def _price(value, where: str, field: str, errors: list) -> Decimal | None:
    if value is None or value == "":
        return None
    try:
        price = Decimal(str(value).replace(",", "").strip())
    except (InvalidOperation, ValueError):
        errors.append({"where": where, "field": field, "message": "Enter a valid price, e.g. 250 or 99.50."})
        return None
    if not price.is_finite() or price < 0 or price > MAX_PRICE or price != price.quantize(Decimal("0.01")):
        errors.append({"where": where, "field": field, "message": "Enter a valid price with at most 2 decimals."})
        return None
    return price.quantize(Decimal("0.01"))


def _validate(payload: dict, store: Store, db: Session) -> tuple[list[dict], list[dict]]:
    errors: list[dict] = []
    raw_categories = payload.get("categories") or []
    raw_items = payload.get("items") or []
    if len(raw_categories) > settings.MAX_CATALOGUE_CATEGORIES:
        errors.append({"where": "catalogue", "field": "categories",
                       "message": f"At most {settings.MAX_CATALOGUE_CATEGORIES} categories."})
    if len(raw_items) > settings.MAX_CATALOGUE_ITEMS:
        errors.append({"where": "catalogue", "field": "items", "message": f"At most {settings.MAX_CATALOGUE_ITEMS} items."})
    if errors:
        raise CatalogueValidationError(errors)

    categories, refs = [], set()
    for idx, raw in enumerate(raw_categories):
        where = f"categories[{idx}]"
        ref = str(raw.get("ref") or raw.get("id") or "")
        name = _str(raw.get("name"), "name", 80, errors, where, required=True)
        if not ref:
            errors.append({"where": where, "field": "ref", "message": "Missing reference."})
        elif ref in refs:
            errors.append({"where": where, "field": "ref", "message": "Duplicate category."})
        refs.add(ref)
        categories.append({"ref": ref, "id": raw.get("id"), "name": name})

    image_ids = {r.get("image_media_id") for r in raw_items if r.get("image_media_id")}
    valid_images = set()
    if image_ids:
        valid_images = {
            m.id for m in db.query(Media.id).filter(
                Media.id.in_(list(image_ids)), Media.store_id == store.id,
                Media.kind == MediaKindEnum.item_image, Media.deleted_at.is_(None),
            ).all()
        }

    items = []
    for idx, raw in enumerate(raw_items):
        where = f"items[{idx}]"
        name = _str(raw.get("name"), "name", 160, errors, where, required=True)
        category_ref = raw.get("category_ref")
        if category_ref is not None and str(category_ref) not in refs:
            errors.append({"where": where, "field": "category", "message": "Unknown category."})
        variants = []
        for v_idx, v in enumerate((raw.get("variants") or [])[:12]):
            v_name = _str(v.get("name"), "variant", 60, errors, f"{where}.variants[{v_idx}]", required=True)
            v_price = _price(v.get("price"), f"{where}.variants[{v_idx}]", "price", errors)
            v_text = _str(v.get("price_text"), "price_text", 40, errors, f"{where}.variants[{v_idx}]")
            variants.append({"name": v_name, "price": str(v_price) if v_price is not None else None,
                             "price_text": None if v_price is not None else v_text})
        labels = raw.get("labels") or []
        if any(lbl not in ITEM_LABELS for lbl in labels):
            errors.append({"where": where, "field": "labels", "message": "Unknown label."})
        image_id = raw.get("image_media_id")
        if image_id and image_id not in valid_images:
            errors.append({"where": where, "field": "image", "message": "Image not found."})
        price = _price(raw.get("price"), where, "price", errors)
        items.append({
            "id": raw.get("id"),
            "category_ref": str(category_ref) if category_ref is not None else None,
            "name": name,
            "description": _str(raw.get("description"), "description", 1000, errors, where),
            "price": price,
            "price_text": None if price is not None else _str(raw.get("price_text"), "price_text", 60, errors, where),
            "variants": variants,
            "labels": sorted(set(labels)),
            "available": bool(raw.get("available", True)),
            "image_media_id": image_id or None,
            "needs_review": bool(raw.get("needs_review", False)),
        })
    if errors:
        raise CatalogueValidationError(errors[:50])
    return categories, items


# ------------------------------------------------------------- hashing ----

def _fingerprint(categories: list[tuple], items: list[tuple]) -> str:
    blob = json.dumps({"c": categories, "i": items}, sort_keys=True, default=str)
    return hashlib.sha256(blob.encode()).hexdigest()


def _current_fingerprint(store: Store) -> str:
    cat_index = {c.id: n for n, c in enumerate(store.categories)}
    return _fingerprint(
        [c.name for c in store.categories],
        [(cat_index.get(i.category_id), i.name, i.description, str(i.price) if i.price is not None else None,
          i.price_text, i.variants, i.labels, i.available, i.image_media_id) for i in store.items],
    )


def _new_fingerprint(categories: list[dict], items: list[dict]) -> str:
    cat_index = {c["ref"]: n for n, c in enumerate(categories)}
    return _fingerprint(
        [c["name"] for c in categories],
        [(cat_index.get(i["category_ref"]), i["name"], i["description"],
          str(i["price"]) if i["price"] is not None else None, i["price_text"], i["variants"], i["labels"],
          i["available"], i["image_media_id"]) for i in items],
    )


# ---------------------------------------------------------------- save ----

def save_catalogue(store_id: str, user: User, payload: dict, db: Session, reason: str = "owner_save") -> dict:
    """Returns {"changed", "counted", "catalogue", "usage"}. Raises
    HTTPException 409 (stale version), 422 (validation) or
    plans.QuotaExceeded (caller maps to 402)."""
    from app.api.deps import load_owned_store
    from app.services import publishing

    store = load_owned_store(store_id, user, db, for_update=True)
    base_version = payload.get("base_version")
    if base_version is not None and int(base_version) != store.catalogue_version:
        db.rollback()
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            "Your catalogue was changed in another tab or by a new import. Reload to see the latest version — your edits are kept in this browser.",
        )
    try:
        categories, items = _validate(payload, store, db)
    except CatalogueValidationError:
        db.rollback()
        raise

    old_fp, new_fp = _current_fingerprint(store), _new_fingerprint(categories, items)
    review_cleared = any(
        i["id"] and not i["needs_review"] and any(e.id == i["id"] and e.needs_review for e in store.items)
        for i in items
    )
    if old_fp == new_fp and not review_cleared:
        db.rollback()
        return {"changed": False, "counted": False, "catalogue": catalogue_out(store, db), "usage": plans.usage_summary(store, db)}

    counted, plan_code = (False, None)
    if old_fp != new_fp:
        counted, plan_code = plans.consume_catalogue_update(store, db)  # may raise QuotaExceeded

    summary = _apply(store, categories, items, db)
    store.catalogue_version += 1
    if old_fp != new_fp:
        db.add(CatalogueRevision(
            store_id=store.id, actor_id=user.id, period=plans.current_period(), counted=counted,
            plan_code=plan_code or plans.resolve_plan(user, db)[0].code, summary={**summary, "reason": reason},
            catalogue_hash=new_fp,
        ))
    db.flush()
    if counted:
        audit(db, user.id, "qr.catalogue.updated", store_id=store.id, **summary)
    publishing.refresh_live_site(store, db)
    db.commit()
    db.refresh(store)
    return {"changed": True, "counted": counted, "catalogue": catalogue_out(store, db), "usage": plans.usage_summary(store, db)}


def _apply(store: Store, categories: list[dict], items: list[dict], db: Session) -> dict:
    existing_cats = {c.id: c for c in store.categories}
    ref_to_id: dict[str, str] = {}
    keep_cat_ids = set()
    for pos, cat in enumerate(categories):
        row = existing_cats.get(cat["id"]) if cat["id"] else None
        if row is None:
            row = CatalogueCategory(store_id=store.id, name=cat["name"], position=pos)
            db.add(row)
            db.flush()
        else:
            row.name, row.position = cat["name"], pos
        keep_cat_ids.add(row.id)
        ref_to_id[cat["ref"]] = row.id

    existing_items = {i.id: i for i in store.items}
    submitted_ids = {i["id"] for i in items if i["id"]}
    removed = 0
    for row in list(store.items):
        if row.id not in submitted_ids:
            db.delete(row)
            removed += 1
    for row in list(store.categories):
        if row.id not in keep_cat_ids:
            db.delete(row)
    db.flush()

    added = updated = 0
    for pos, data in enumerate(items):
        row = existing_items.get(data["id"]) if data["id"] else None
        fields = {
            "category_id": ref_to_id.get(data["category_ref"]) if data["category_ref"] else None,
            "name": data["name"], "description": data["description"], "price": data["price"],
            "price_text": data["price_text"], "variants": data["variants"], "labels": data["labels"],
            "available": data["available"], "image_media_id": data["image_media_id"],
        }
        if row is None:
            row = CatalogueItem(store_id=store.id, position=pos, source="manual", **fields)
            db.add(row)
            added += 1
        else:
            changed = any(getattr(row, k) != v for k, v in fields.items())
            for k, v in fields.items():
                setattr(row, k, v)
            row.position = pos
            if changed:
                row.user_edited = True
                updated += 1
            # Clients may only clear the review flag (by editing or confirming), never set it.
            if row.needs_review and (changed or not data["needs_review"]):
                row.needs_review, row.review_reasons = False, []

    db.flush()
    db.expire(store, ["items", "categories"])
    return {"added": added, "updated": updated, "removed": removed, "items": len(items), "categories": len(categories)}


# --------------------------------------------------------- AI import ----

def _crop_item_image(source: Media, box: list[int], store: Store, db: Session) -> str | None:
    """Crops a product photo the AI located in the catalogue page (0-1000 grid)."""
    try:
        img = Image.open(io.BytesIO(media_service.read_bytes(source)))
        img.load()
    except Exception:
        return None
    x0, y0, x1, y1 = box
    if not (0 <= x0 < x1 <= 1000 and 0 <= y0 < y1 <= 1000):
        return None
    left, top = int(x0 / 1000 * img.width), int(y0 / 1000 * img.height)
    right, bottom = int(x1 / 1000 * img.width), int(y1 / 1000 * img.height)
    if right - left < 96 or bottom - top < 96:
        return None
    if (right - left) * (bottom - top) > 0.6 * img.width * img.height:
        return None  # whole-page "crops" are not product photos
    try:
        media = media_service.save_pil_image(db, store.id, img.crop((left, top, right, bottom)),
                                             MediaKindEnum.item_image, origin="catalogue_crop")
    except media_service.MediaError:
        return None
    return media.id


def import_from_job(store_id: str, user: User, mode: str, db: Session) -> dict:
    """
    Writes the latest finished job's extracted items into the catalogue.
    mode="replace" replaces AI-sourced items that the owner hasn't edited
    (manual and owner-edited items are always kept); mode="append" adds.
    Allowed only before the first publish: after that, extraction results
    are reviewed in the editor and saved via save_catalogue (and counted).
    """
    from app.ai.jobs import latest_job
    from app.api.deps import load_owned_store

    store = load_owned_store(store_id, user, db, for_update=True)
    if store.ever_published:
        db.rollback()
        raise HTTPException(status.HTTP_409_CONFLICT,
                            "Your store is live. Add extracted items from the catalogue editor and save to publish them.")
    job: ExtractionJob | None = latest_job(store.id, db)
    if not job or job.status not in (JobStatusEnum.succeeded, JobStatusEnum.partial):
        db.rollback()
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "There are no extracted items to import yet.")

    if mode == "replace":
        for row in list(store.items):
            if row.source == "ai" and not row.user_edited:
                db.delete(row)
        db.flush()
        db.expire(store, ["items"])

    cats_by_name = {c.name.casefold(): c for c in store.categories}
    position = len(store.items)
    imported = flagged = 0
    for page in job.pages:
        if page["status"] != "succeeded" or not page.get("result"):
            continue
        source = db.get(Media, page["media_id"])
        for item in page["result"]["items"]:
            if position >= settings.MAX_CATALOGUE_ITEMS:
                break
            section = item.get("section") or "Other"
            cat = cats_by_name.get(section.casefold())
            if cat is None:
                if len(cats_by_name) >= settings.MAX_CATALOGUE_CATEGORIES:
                    cat = next(iter(cats_by_name.values()))
                else:
                    cat = CatalogueCategory(store_id=store.id, name=section[:80], position=len(cats_by_name))
                    db.add(cat)
                    db.flush()
                    cats_by_name[section.casefold()] = cat
            image_id = _crop_item_image(source, item["image_box"], store, db) if source and item.get("image_box") else None
            db.add(CatalogueItem(
                store_id=store.id, category_id=cat.id, name=item["name"], description=item["description"],
                price=Decimal(item["price"]) if item["price"] is not None else None, price_text=item["price_text"],
                variants=item["variants"], labels=item["labels"], available=True, position=position,
                image_media_id=image_id, source="ai", source_media_id=page["media_id"],
                needs_review=item["needs_review"], review_reasons=item["review_reasons"],
                confidence=item["confidence"],
            ))
            position += 1
            imported += 1
            flagged += int(item["needs_review"])

    result = job.result or {}
    if result.get("currency") and not store.items:
        store.currency = result["currency"]
    store.catalogue_version += 1
    if store.onboarding_step in ("upload", "category", "business", "template", "catalogue"):
        store.onboarding_step = "catalogue"
    audit(db, user.id, "qr.catalogue.imported", store_id=store.id, job_id=job.id, items=imported, flagged=flagged, mode=mode)
    db.commit()
    db.refresh(store)
    return {"imported": imported, "flagged": flagged, "catalogue": catalogue_out(store, db)}


def extracted_items_preview(job: ExtractionJob | None) -> list[dict]:
    """Extracted items not yet imported — shown in the editor so a live store
    can add them through a normal (counted) save."""
    if not job or job.status not in (JobStatusEnum.succeeded, JobStatusEnum.partial):
        return []
    out = []
    for page in job.pages:
        if page["status"] == "succeeded" and page.get("result"):
            for item in page["result"]["items"]:
                out.append({k: item[k] for k in ("name", "section", "description", "price", "price_text",
                                                 "variants", "labels", "needs_review", "review_reasons")})
    return out
