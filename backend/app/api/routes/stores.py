"""
Owner-facing store APIs (all under /api/qr, all tenant-scoped through
get_owned_store / load_owned_store).
"""
from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, Response, UploadFile, status
from fastapi.responses import HTMLResponse
from sqlalchemy.orm import Session

from app.ai import jobs
from app.api.deps import get_current_user, get_owned_store, load_owned_store
from app.catalog.registry import TEMPLATE_BY_KEY, meta_payload, templates_for
from app.core.config import settings
from app.core.ratelimit import limit_by_user
from app.db.session import get_db
from app.models.models import Media, MediaKindEnum, Store, StoreDailyStat, TableCode, User
from app.schemas import (
    BrandingIn,
    CatalogueSaveIn,
    ImportIn,
    SourceOrderIn,
    StoreCreateIn,
    TableCodeIn,
    StoreUpdateIn,
    WhatsappProofIn,
)
from app.services import catalogue as catalogue_service
from app.services import media as media_service
from app.services import plans, publishing, qr, slugs, stores
from app.services.audit import audit

router = APIRouter(prefix="/api/qr", tags=["qr-stores"])

upload_limit = limit_by_user("upload", 40, 600)
ai_limit = limit_by_user("ai", 10, 3600)
write_limit = limit_by_user("write", 120, 600)


def _quota_response(exc: plans.QuotaExceeded) -> HTTPException:
    usage = exc.usage
    return HTTPException(status.HTTP_402_PAYMENT_REQUIRED, {
        "code": "quota_exceeded",
        "message": f"You've used all {usage['limit']} catalogue updates for this month. "
                   "Your changes are still here — upgrade to save them now, or save after your limit resets.",
        "usage": usage,
    })


# ------------------------------------------------------------------ meta ----

@router.get("/meta")
def get_meta(current_user: User = Depends(get_current_user)):
    return {**meta_payload(), "base_domain": settings.BASE_DOMAIN,
            "max_upload_mb": settings.MAX_UPLOAD_BYTES // (1024 * 1024), "max_source_images": settings.MAX_SOURCE_IMAGES}


@router.get("/plans")
def list_plans(current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    plan, valid_until, source = plans.resolve_plan(current_user, db)
    return {
        "plans": plans.plans_out(db),
        "current": {"code": plan.code, "valid_until": valid_until, "source": source},
        "upgrade": {
            # Kept for older clients: the Pro-only offer.
            "available": settings.QR_STORE_PRO_PRICE_RUPEES > 0,
            "product": settings.PAID_PLAN_PRODUCT,
            "price_rupees": settings.QR_STORE_PRO_PRICE_RUPEES or None,
            "duration_days": settings.PAID_PLAN_DURATION_DAYS,
        },
        # What can be bought; each option maps to a billing product. Price 0 = not sold.
        "offers": [
            {"plan_code": code, "product": product, "price_rupees": price}
            for code, product, price in (
                (settings.SPLIT_PLAN_CODE, settings.SPLIT_PLAN_PRODUCT, settings.QR_SPLIT_BILL_PRICE_RUPEES),
                (settings.PAID_PLAN_CODE, settings.PAID_PLAN_PRODUCT, settings.QR_STORE_PRO_PRICE_RUPEES),
                (settings.PRO_SPLIT_PLAN_CODE, settings.PRO_SPLIT_PLAN_PRODUCT, settings.QR_PRO_SPLIT_PRICE_RUPEES),
            ) if price > 0
        ],
    }


# ---------------------------------------------------------------- stores ----

@router.get("/stores")
def my_stores(current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    rows = db.query(Store).filter(Store.owner_id == current_user.id).order_by(Store.created_at).all()
    return {"stores": [stores.store_summary(s) for s in rows], "max_stores": settings.MAX_STORES_PER_USER}


@router.post("/stores", status_code=status.HTTP_201_CREATED)
def create_store(payload: StoreCreateIn, current_user: User = Depends(write_limit), db: Session = Depends(get_db)):
    store = stores.create_store(current_user, payload.name, db)
    return stores.store_out(store, db)


@router.get("/stores/{store_id}")
def get_store(store: Store = Depends(get_owned_store), db: Session = Depends(get_db)):
    return stores.store_out(store, db)


@router.patch("/stores/{store_id}")
def update_store(
    store_id: str, payload: StoreUpdateIn, current_user: User = Depends(write_limit), db: Session = Depends(get_db)
):
    store = load_owned_store(store_id, current_user, db, for_update=True)
    data = payload.model_dump(exclude_unset=True)
    store = stores.update_store(store, current_user, data, db)
    if "category_key" in data:
        job = jobs.latest_job(store.id, db)
        suggested = ((job.result or {}).get("category") or {}).get("suggested") if job else None
        if suggested and suggested == store.category_key:
            store.category_source = "ai"
            db.commit()
    return stores.store_out(store, db)


@router.get("/stores/{store_id}/slug-availability")
def slug_availability(slug: str = Query(max_length=100), store: Store = Depends(get_owned_store), db: Session = Depends(get_db)):
    return slugs.check_availability(slug, db, exclude_store_id=store.id)


@router.get("/stores/{store_id}/slug-suggestion")
def slug_suggestion(name: str = Query(max_length=120), store: Store = Depends(get_owned_store), db: Session = Depends(get_db)):
    base = slugs.normalize_slug(name)
    if base:
        result = slugs.check_availability(base, db, exclude_store_id=store.id)
        if result["available"]:
            return {"slug": base}
    alternatives = slugs.suggest_alternatives(base or "my-store", db, store.id, count=1)
    return {"slug": alternatives[0] if alternatives else None}


@router.post("/stores/{store_id}/whatsapp/verify")
def verify_whatsapp(store_id: str, payload: WhatsappProofIn, current_user: User = Depends(write_limit), db: Session = Depends(get_db)):
    store = load_owned_store(store_id, current_user, db, for_update=True)
    store = stores.apply_whatsapp_proof(store, current_user, payload.proof_token, db)
    return stores.store_out(store, db)


# --------------------------------------------------------- source photos ----

@router.post("/stores/{store_id}/sources", status_code=status.HTTP_201_CREATED)
def upload_sources(
    store_id: str,
    files: list[UploadFile] = File(...),
    current_user: User = Depends(upload_limit),
    db: Session = Depends(get_db),
):
    store = load_owned_store(store_id, current_user, db, for_update=True)
    existing = jobs.source_pages(store.id, db)
    if len(existing) + len(files) > settings.MAX_SOURCE_IMAGES:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY,
                            f"You can upload up to {settings.MAX_SOURCE_IMAGES} photos per store.")
    created, errors = [], []
    position = max((m.position for m in existing), default=-1) + 1
    for upload in files:
        raw = upload.file.read(settings.MAX_UPLOAD_BYTES + 1)
        try:
            media = media_service.save_image(db, store.id, raw, MediaKindEnum.source, position=position)
            created.append(media)
            position += 1
        except media_service.MediaError as exc:
            errors.append({"filename": (upload.filename or "")[:100], "message": str(exc)})
    if created:
        audit(db, current_user.id, "qr.sources.uploaded", store_id=store.id, count=len(created))
    db.commit()
    if not created:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, {"message": errors[0]["message"], "errors": errors})
    return {"sources": [media_service.media_out(m) for m in jobs.source_pages(store.id, db)], "errors": errors}


@router.delete("/stores/{store_id}/sources/{media_id}")
def delete_source(store_id: str, media_id: str, current_user: User = Depends(write_limit), db: Session = Depends(get_db)):
    store = load_owned_store(store_id, current_user, db, for_update=True)
    media = db.query(Media).filter(Media.id == media_id, Media.store_id == store.id, Media.kind == MediaKindEnum.source).first()
    if not media:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Photo not found")
    media_service.delete_files(media)
    db.delete(media)
    db.commit()
    return {"sources": [media_service.media_out(m) for m in jobs.source_pages(store.id, db)]}


@router.put("/stores/{store_id}/sources/order")
def reorder_sources(store_id: str, payload: SourceOrderIn, current_user: User = Depends(write_limit), db: Session = Depends(get_db)):
    store = load_owned_store(store_id, current_user, db, for_update=True)
    pages = {m.id: m for m in jobs.source_pages(store.id, db)}
    if set(payload.media_ids) != set(pages):
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "Photo list is out of date. Please reload.")
    for pos, mid in enumerate(payload.media_ids):
        pages[mid].position = pos
    db.commit()
    return {"sources": [media_service.media_out(m) for m in jobs.source_pages(store.id, db)]}


# -------------------------------------------------------------- analysis ----

@router.post("/stores/{store_id}/analysis", status_code=status.HTTP_202_ACCEPTED)
def start_analysis(store_id: str, current_user: User = Depends(ai_limit), db: Session = Depends(get_db)):
    store = load_owned_store(store_id, current_user, db)
    job = jobs.start_job(store, current_user.id, db)
    db.refresh(job)
    return jobs.job_out(job)


@router.post("/stores/{store_id}/analysis/retry", status_code=status.HTTP_202_ACCEPTED)
def retry_analysis(store_id: str, current_user: User = Depends(ai_limit), db: Session = Depends(get_db)):
    store = load_owned_store(store_id, current_user, db)
    job = jobs.retry_job(store, db)
    db.refresh(job)
    return jobs.job_out(job)


@router.get("/stores/{store_id}/analysis")
def get_analysis(store: Store = Depends(get_owned_store), db: Session = Depends(get_db)):
    return {"job": jobs.job_out(jobs.latest_job(store.id, db))}


# ------------------------------------------------------------- catalogue ----

@router.get("/stores/{store_id}/catalogue")
def get_catalogue(store: Store = Depends(get_owned_store), db: Session = Depends(get_db)):
    out = catalogue_service.catalogue_out(store, db)
    out["usage"] = plans.usage_summary(store, db)
    out["extracted"] = catalogue_service.extracted_items_preview(jobs.latest_job(store.id, db)) if store.ever_published else []
    return out


@router.put("/stores/{store_id}/catalogue")
def save_catalogue(store_id: str, payload: CatalogueSaveIn, current_user: User = Depends(write_limit), db: Session = Depends(get_db)):
    try:
        return catalogue_service.save_catalogue(store_id, current_user, payload.model_dump(), db)
    except catalogue_service.CatalogueValidationError as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, {"message": "Please fix the highlighted items.", "errors": exc.errors})
    except plans.QuotaExceeded as exc:
        db.rollback()
        raise _quota_response(exc)


@router.post("/stores/{store_id}/catalogue/import")
def import_catalogue(store_id: str, payload: ImportIn, current_user: User = Depends(write_limit), db: Session = Depends(get_db)):
    return catalogue_service.import_from_job(store_id, current_user, payload.mode, db)


@router.post("/stores/{store_id}/media", status_code=status.HTTP_201_CREATED)
def upload_media(
    store_id: str,
    kind: str = Form(...),
    file: UploadFile = File(...),
    crop_x: int | None = Form(None),
    crop_y: int | None = Form(None),
    crop_w: int | None = Form(None),
    crop_h: int | None = Form(None),
    current_user: User = Depends(upload_limit),
    db: Session = Depends(get_db),
):
    if kind not in ("item_image", "logo", "banner"):
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "Unknown image type.")
    store = load_owned_store(store_id, current_user, db)
    crop = None
    if None not in (crop_x, crop_y, crop_w, crop_h):
        crop = (crop_x, crop_y, crop_x + crop_w, crop_y + crop_h)
    raw = file.file.read(settings.MAX_UPLOAD_BYTES + 1)
    try:
        media = media_service.save_image(db, store.id, raw, MediaKindEnum(kind), crop=crop)
    except media_service.MediaError as exc:
        db.rollback()
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, str(exc))
    db.commit()
    return media_service.media_out(media)


# -------------------------------------------------------------- branding ----

@router.put("/stores/{store_id}/branding")
def update_branding(store_id: str, payload: BrandingIn, current_user: User = Depends(write_limit), db: Session = Depends(get_db)):
    store = load_owned_store(store_id, current_user, db, for_update=True)
    store = stores.update_branding(store, current_user, payload.model_dump(exclude_unset=True), db)
    return stores.store_out(store, db)


# ------------------------------------------------- preview / publish / QR ----

@router.get("/stores/{store_id}/templates")
def store_templates(store: Store = Depends(get_owned_store)):
    ordered = templates_for(store.category_key)
    return {"templates": [{"key": t.key, "name": t.name, "description": t.description, "highlights": t.highlights,
                           "recommended": bool(store.category_key) and t.key == ordered[0].key}
                          for t in ordered]}


@router.get("/stores/{store_id}/preview", response_class=HTMLResponse)
def preview(template: str | None = Query(None, max_length=50), store: Store = Depends(get_owned_store), db: Session = Depends(get_db)):
    if template and template not in TEMPLATE_BY_KEY:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Unknown design")
    html = publishing.render_html(store, db, mode="preview", template_key=template)
    return HTMLResponse(html, headers={"Cache-Control": "no-store", "X-Robots-Tag": "noindex"})


@router.post("/stores/{store_id}/publish")
def publish(store_id: str, current_user: User = Depends(write_limit), db: Session = Depends(get_db)):
    store = load_owned_store(store_id, current_user, db, for_update=True)
    store = publishing.publish(store, current_user, db)
    return stores.store_out(store, db)


@router.post("/stores/{store_id}/unpublish")
def unpublish(store_id: str, current_user: User = Depends(write_limit), db: Session = Depends(get_db)):
    store = load_owned_store(store_id, current_user, db, for_update=True)
    store = publishing.unpublish(store, current_user, db)
    return stores.store_out(store, db)


@router.get("/stores/{store_id}/qr")
def download_qr(
    format: str = Query("png", pattern="^(png|svg)$"),
    layout: str = Query("card", pattern="^(card|plain)$"),
    size: str = Query("digital", pattern="^(digital|print)$"),
    table_id: str | None = Query(None, max_length=36),
    store: Store = Depends(get_owned_store),
    db: Session = Depends(get_db),
):
    if not store.slug:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Choose your store address first.")
    url = settings.public_store_url(store.slug)
    table_no = None
    if table_id:
        table = _get_table(store, table_id, db)
        table_no = table.table_no
        url = qr.table_url(url, table_no)
    name = store.name or store.slug
    color = (store.branding or {}).get("primary")
    table_part = "-table-" + "".join(c if c.isalnum() else "_" for c in table_no) if table_no else ""
    filename = f"{store.slug}-qr{table_part}-{layout}{'-print' if size == 'print' and format == 'png' else ''}.{format}"
    headers = {"Content-Disposition": f'attachment; filename="{filename}"', "Cache-Control": "no-store"}
    if format == "svg":
        return Response(qr.render_svg(url, name, color, layout, table_no), media_type="image/svg+xml", headers=headers)
    try:
        data = qr.render_png(url, name, color, layout, size, table_no)
    except qr.QrError:
        raise HTTPException(status.HTTP_500_INTERNAL_SERVER_ERROR, "We couldn't generate a scannable QR code. Please try again.")
    return Response(data, media_type="image/png", headers=headers)


# ------------------------------------------------- sitting-area tables ----

MAX_TABLES = 200


def _table_out(t: TableCode) -> dict:
    return {"id": t.id, "table_no": t.table_no}


def _get_table(store: Store, table_id: str, db: Session) -> TableCode:
    try:
        table = db.query(TableCode).filter(TableCode.id == table_id, TableCode.store_id == store.id).first()
    except Exception:  # malformed UUID
        db.rollback()
        table = None
    if not table:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Table not found")
    return table


def _clean_table_no(raw: str) -> tuple[str, str]:
    value = " ".join(raw.split())
    if not value or any(ord(c) < 32 for c in value):
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "Enter a table number.")
    return value, value.casefold()


def _ensure_unique(store: Store, key: str, db: Session, exclude_id: str | None = None) -> None:
    q = db.query(TableCode.id).filter(TableCode.store_id == store.id, TableCode.table_key == key)
    if exclude_id:
        q = q.filter(TableCode.id != exclude_id)
    if q.first():
        raise HTTPException(status.HTTP_409_CONFLICT, "That table number already has a QR code.")


@router.get("/stores/{store_id}/tables")
def list_tables(store: Store = Depends(get_owned_store), db: Session = Depends(get_db)):
    rows = db.query(TableCode).filter(TableCode.store_id == store.id).order_by(TableCode.created_at, TableCode.id).all()
    return [_table_out(t) for t in rows]


@router.post("/stores/{store_id}/tables", status_code=status.HTTP_201_CREATED)
def create_table(store_id: str, payload: TableCodeIn, current_user: User = Depends(write_limit), db: Session = Depends(get_db)):
    store = load_owned_store(store_id, current_user, db, for_update=True)
    value, key = _clean_table_no(payload.table_no)
    if db.query(TableCode).filter(TableCode.store_id == store.id).count() >= MAX_TABLES:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, f"You can add up to {MAX_TABLES} tables.")
    _ensure_unique(store, key, db)
    table = TableCode(store_id=store.id, table_no=value, table_key=key)
    db.add(table)
    audit(db, current_user.id, "qr.table.created", store_id=store.id, table_no=value)
    db.commit()
    return _table_out(table)


@router.patch("/stores/{store_id}/tables/{table_id}")
def update_table(store_id: str, table_id: str, payload: TableCodeIn, current_user: User = Depends(write_limit), db: Session = Depends(get_db)):
    store = load_owned_store(store_id, current_user, db, for_update=True)
    table = _get_table(store, table_id, db)
    value, key = _clean_table_no(payload.table_no)
    _ensure_unique(store, key, db, exclude_id=table.id)
    table.table_no, table.table_key = value, key
    audit(db, current_user.id, "qr.table.updated", store_id=store.id, table_no=value)
    db.commit()
    return _table_out(table)


@router.delete("/stores/{store_id}/tables/{table_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_table(store_id: str, table_id: str, current_user: User = Depends(write_limit), db: Session = Depends(get_db)):
    store = load_owned_store(store_id, current_user, db, for_update=True)
    table = _get_table(store, table_id, db)
    audit(db, current_user.id, "qr.table.deleted", store_id=store.id, table_no=table.table_no)
    db.delete(table)
    db.commit()


# ----------------------------------------------------------- usage/stats ----

@router.get("/stores/{store_id}/usage")
def usage(store: Store = Depends(get_owned_store), db: Session = Depends(get_db)):
    return plans.usage_summary(store, db)


@router.get("/stores/{store_id}/activity")
def activity(store: Store = Depends(get_owned_store), db: Session = Depends(get_db)):
    rows = (
        db.query(StoreDailyStat)
        .filter(StoreDailyStat.store_id == store.id)
        .order_by(StoreDailyStat.day.desc())
        .limit(30)
        .all()
    )
    days = [{"day": r.day.isoformat(), "views": r.views, "item_enquiries": r.item_enquiries, "cart_enquiries": r.cart_enquiries}
            for r in reversed(rows)]
    return {
        "days": days,
        "totals": {k: sum(d[k] for d in days) for k in ("views", "item_enquiries", "cart_enquiries")},
        "note": "WhatsApp enquiries count taps that opened WhatsApp; customers still choose whether to send.",
    }
