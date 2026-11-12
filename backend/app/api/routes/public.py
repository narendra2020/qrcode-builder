"""
Unauthenticated endpoints: signed private-media delivery for the owner
dashboard, anonymous storefront counters, and host-based store resolution.
"""
from datetime import datetime
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends, Header, HTTPException, Query, Request, status
from fastapi.responses import FileResponse
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.ratelimit import limit_by_ip
from app.core.security import verify_media_signature
from app.db.session import get_db
from app.models.models import Store, StoreDailyStat, StoreStatusEnum
from app.services import media as media_service
from app.services import slugs

router = APIRouter(prefix="/api/qr", tags=["qr-public"])

_MIME = {"jpg": "image/jpeg", "png": "image/png", "webp": "image/webp"}
_COLUMN = {"view": "views", "item_enquiry": "item_enquiries", "cart_enquiry": "cart_enquiries"}


@router.get("/media/file/{rel_path:path}", include_in_schema=False)
def media_file(rel_path: str, exp: int = Query(...), sig: str = Query(..., max_length=128)):
    if not verify_media_signature(rel_path, exp, sig):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "This link has expired. Reload the page.")
    try:
        path = media_service.abs_path(rel_path)
    except media_service.MediaError:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Not found")
    if not path.is_file():
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Not found")
    return FileResponse(path, media_type=_MIME.get(path.suffix.lstrip("."), "application/octet-stream"),
                        headers={"Cache-Control": "private, max-age=600", "X-Content-Type-Options": "nosniff"})


def slug_from_host(host: str | None) -> str | None:
    """'fresh-bites.mepage.in[:port]' -> 'fresh-bites'; anything else -> None."""
    if not host:
        return None
    host = host.split(":", 1)[0].strip().lower().rstrip(".")
    suffix = "." + settings.BASE_DOMAIN.lower()
    if not host.endswith(suffix):
        return None
    label = host[: -len(suffix)]
    if "." in label:
        return None
    try:
        slugs.validate_slug(label)
    except slugs.SlugError:
        return None
    return label


def published_store(slug: str | None, db: Session) -> Store | None:
    if not slug:
        return None
    return db.query(Store).filter(Store.slug == slug, Store.status == StoreStatusEnum.published).first()


@router.get("/public/resolve", dependencies=[Depends(limit_by_ip("public-resolve", 120, 60))])
def resolve(host: str | None = Header(default=None), db: Session = Depends(get_db)):
    """Resolves the requesting storefront host to its public store record."""
    store = published_store(slug_from_host(host), db)
    if not store:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Store not found")
    return {"slug": store.slug, "name": store.name, "url": settings.public_store_url(store.slug)}


@router.post("/public/events", status_code=status.HTTP_204_NO_CONTENT,
             dependencies=[Depends(limit_by_ip("public-events", 60, 60))])
async def record_event(request: Request, db: Session = Depends(get_db)):
    """Anonymous counters only (no IP, cookies or message contents stored)."""
    try:
        body = await request.json()
    except Exception:
        return
    if not isinstance(body, dict):
        return
    slug, kind = str(body.get("slug", ""))[:63], body.get("kind")
    column = _COLUMN.get(kind)
    if not column:
        return
    store = published_store(slug, db)
    if not store:
        return
    day = datetime.now(ZoneInfo(settings.QUOTA_TIMEZONE)).date()
    stmt = pg_insert(StoreDailyStat).values(store_id=store.id, day=day, **{column: 1})
    stmt = stmt.on_conflict_do_update(
        index_elements=["store_id", "day"], set_={column: getattr(StoreDailyStat.__table__.c, column) + 1}
    )
    db.execute(stmt)
    db.commit()
