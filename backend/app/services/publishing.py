"""
Storefront rendering, publish / unpublish, and readiness checks.

The storefront is rendered from structured catalogue rows (never from AI
HTML) through the store's template, then written as a static site to
PUBLISHED_SITES_DIR/<slug>/ — the same directory and wildcard
*.BASE_DOMAIN host that already serve portfolio-builder sites, so no new
routing tier is needed. Images are copied into the site (published media
becomes public only at this point); everything else stays private.

The same renderer produces owner previews (mode="preview") with signed
media URLs and inlined assets, so the preview is exactly what customers
will get.
"""
import hashlib
import json
import os
import shutil
import tempfile
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path

from fastapi import HTTPException, status
from jinja2 import Environment, FileSystemLoader, select_autoescape
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.catalog.registry import ITEM_LABELS, TEMPLATE_BY_KEY, get_category, templates_for
from app.core.config import settings
from app.models.models import Media, Store, StoreStatusEnum, User
from app.services import branding as branding_service
from app.services import media as media_service
from app.services import qr as qr_service
from app.services import slugs
from app.services.audit import audit
from app.services.whatsapp import item_price_label

TEMPLATE_DIR = Path(__file__).resolve().parent.parent / "templates" / "storefront"
STATIC_DIR = TEMPLATE_DIR / "static"

_env = Environment(
    loader=FileSystemLoader(str(TEMPLATE_DIR)),
    autoescape=select_autoescape(["html", "j2"]),
    trim_blocks=True,
    lstrip_blocks=True,
)


def _now() -> datetime:
    return datetime.now(timezone.utc)


# ------------------------------------------------------------ readiness ----

def readiness(store: Store, db: Session) -> list[dict]:
    """Blocking problems that must be fixed before publishing."""
    issues = []
    if not store.name:
        issues.append({"step": "business", "message": "Add your store name."})
    if not store.slug:
        issues.append({"step": "business", "message": "Choose your store web address."})
    if not store.whatsapp_number or not store.whatsapp_verified:
        issues.append({"step": "business", "message": "Add and verify the WhatsApp number that receives enquiries."})
    if not store.category_key:
        issues.append({"step": "category", "message": "Choose your business category."})
    if not store.template_key or store.template_key not in TEMPLATE_BY_KEY:
        issues.append({"step": "template", "message": "Choose a storefront design."})
    if not store.items:
        issues.append({"step": "catalogue", "message": "Add at least one item to your catalogue."})
    review = sum(1 for i in store.items if i.needs_review)
    if review:
        issues.append({"step": "catalogue",
                       "message": f"Review {review} item(s) the AI wasn't sure about before publishing."})
    return issues


# ------------------------------------------------------------- context ----

class _ImageResolver:
    """Maps media ids to URLs: signed URLs for previews, copied files for published sites."""

    def __init__(self, db: Session, store: Store, mode: str, dest: Path | None):
        self.db, self.store, self.mode, self.dest = db, store, mode, dest
        ids = [i.image_media_id for i in store.items if i.image_media_id]
        ids += [store.branding.get(k) for k in ("logo_media_id", "banner_media_id") if store.branding.get(k)]
        rows = db.query(Media).filter(Media.id.in_(ids), Media.store_id == store.id, Media.deleted_at.is_(None)).all() if ids else []
        self.media = {m.id: m for m in rows}

    def _url(self, rel: str) -> str:
        if self.mode == "preview":
            from app.core.security import sign_media_path
            exp, sig = sign_media_path(rel)
            return f"/api/qr/media/file/{rel}?exp={exp}&sig={sig}"
        name = rel.rsplit("/", 1)[-1]
        target = self.dest / "assets" / "img" / name
        if not target.exists():
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(media_service.abs_path(rel), target)
        return f"assets/img/{name}"

    def image(self, media_id: str | None) -> dict | None:
        m = self.media.get(media_id or "")
        if not m:
            return None
        srcset = ", ".join(f"{self._url(rel)} {w}w" for w, rel in sorted(m.variants.items(), key=lambda kv: int(kv[0])))
        src = self._url(m.path)
        return {"src": src, "srcset": f"{srcset}, {src} {m.width}w" if srcset else None,
                "width": m.width, "height": m.height}


def _context(store: Store, db: Session, mode: str, dest: Path | None, template_key: str | None = None) -> dict:
    template_key = template_key or store.template_key or templates_for(store.category_key)[0].key
    category = get_category(store.category_key)
    theme = branding_service.theme(store.branding, template_key)
    images = _ImageResolver(db, store, mode, dest)
    store_url = settings.public_store_url(store.slug) if store.slug else settings.public_store_url("your-store")

    cats = [{"id": c.id, "name": c.name, "items": []} for c in store.categories]
    by_id = {c["id"]: c for c in cats}
    uncategorised = {"id": "other", "name": "More", "items": []}
    items_json = []
    for item in store.items:
        price_label = item_price_label(item.price, item.price_text, store.currency)
        variants = [
            {"name": v["name"], "label": item_price_label(Decimal(v["price"]) if v.get("price") else None,
                                                          v.get("price_text"), store.currency)}
            for v in item.variants
        ]
        entry = {
            "id": item.id, "name": item.name, "description": item.description,
            "price_label": price_label, "variants": variants, "available": item.available,
            "labels": [{"key": lbl, "text": ITEM_LABELS[lbl]} for lbl in item.labels if lbl in ITEM_LABELS],
            "image": images.image(item.image_media_id),
        }
        (by_id.get(item.category_id) or uncategorised)["items"].append(entry)
        items_json.append({
            "id": item.id, "name": item.name, "available": item.available,
            "price": str(item.price) if item.price is not None else None, "price_text": item.price_text,
            "search": " ".join([item.name, item.description or "", *(v["name"] for v in variants)]),
        })
    if uncategorised["items"]:
        cats.append(uncategorised)
    cats = [c for c in cats if c["items"]]

    from app.services import payments

    split_bill = payments.split_bill_active(store)
    address = ", ".join(p for p in (store.address_line, store.city, store.state, store.postal_code, store.country) if p)
    description = store.description or store.tagline or f"{category.catalogue_noun} of {store.name} — browse and enquire on WhatsApp."
    return {
        "mode": mode,
        "split_bill": split_bill,
        "store": {
            "name": store.name or "Your store", "tagline": store.tagline, "description": store.description,
            "address": address or None, "city": store.city, "phone": store.contact_phone, "email": store.email,
            "opening_hours": store.opening_hours, "maps_url": store.maps_url, "url": store_url,
            "zomato_url": store.zomato_url, "swiggy_url": store.swiggy_url,
            "currency": store.currency, "whatsapp": (store.whatsapp_number or "").lstrip("+"),
        },
        "meta_description": description[:160],
        "category": category,
        "categories": cats,
        "item_count": sum(len(c["items"]) for c in cats),
        "theme": theme,
        "logo": images.image(store.branding.get("logo_media_id")),
        "banner": images.image(store.branding.get("banner_media_id")),
        "store_json": {
            "slug": store.slug, "name": store.name or "Your store", "url": store_url,
            "whatsapp": (store.whatsapp_number or "").lstrip("+"), "currency": store.currency,
            "items": items_json, "eventsUrl": "/api/qr/public/events", "preview": mode == "preview",
            "splitBill": {"enabled": split_bill, "url": f"/api/qr/public/stores/{store.slug}/split-bills" if store.slug else None},
        },
        "template_key": template_key,
        "placeholder_icon": category.icon,
        "item_noun": category.item_noun,
        "catalogue_noun": category.catalogue_noun,
        "year": _now().year,
        "brand_url": settings.MEPAGE_BRAND_URL,
    }


def _asset_version() -> str:
    """Short content hash appended to asset URLs so browsers never reuse a stale store.js/css."""
    h = hashlib.sha1()
    for name in ("store.css", "store.js", "split.js"):
        h.update((STATIC_DIR / name).read_bytes())
    return h.hexdigest()[:10]


def render_html(store: Store, db: Session, mode: str = "preview", dest: Path | None = None, template_key: str | None = None) -> str:
    ctx = _context(store, db, mode, dest, template_key)
    template = TEMPLATE_BY_KEY[ctx["template_key"]]
    ctx["asset_v"] = _asset_version()
    if mode == "preview":
        ctx["inline_css"] = (STATIC_DIR / "store.css").read_text(encoding="utf-8")
        ctx["inline_js"] = (STATIC_DIR / "store.js").read_text(encoding="utf-8")
        ctx["inline_split_js"] = (STATIC_DIR / "split.js").read_text(encoding="utf-8")
    return _env.get_template(template.file).render(**ctx)


# ------------------------------------------------------------- publish ----

def _site_dir(slug: str) -> Path:
    return Path(settings.PUBLISHED_SITES_DIR) / slug


def _write_site(store: Store, db: Session) -> None:
    """Renders into a temp dir, then swaps it in so visitors never see a half-written site."""
    root = Path(settings.PUBLISHED_SITES_DIR)
    root.mkdir(parents=True, exist_ok=True)
    tmp = Path(tempfile.mkdtemp(prefix=f".{store.slug}-", dir=root))
    try:
        html = render_html(store, db, mode="published", dest=tmp)
        (tmp / "index.html").write_text(html, encoding="utf-8")
        assets = tmp / "assets"
        assets.mkdir(exist_ok=True)
        shutil.copy2(STATIC_DIR / "store.css", assets / "store.css")
        shutil.copy2(STATIC_DIR / "store.js", assets / "store.js")
        shutil.copy2(STATIC_DIR / "split.js", assets / "split.js")
        url = settings.public_store_url(store.slug)
        color = (store.branding or {}).get("primary")
        (assets / "qr.png").write_bytes(qr_service.render_png(url, store.name, color, "card", "digital"))
        (tmp / "robots.txt").write_text(f"User-agent: *\nAllow: /\nSitemap: {url}/sitemap.xml\n", encoding="utf-8")
        (tmp / "sitemap.xml").write_text(
            f'<?xml version="1.0" encoding="UTF-8"?><urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">'
            f"<url><loc>{url}/</loc><lastmod>{_now().date().isoformat()}</lastmod></url></urlset>", encoding="utf-8")
        os.chmod(tmp, 0o755)
        final = _site_dir(store.slug)
        old = None
        if final.exists():
            old = root / f".old-{store.slug}-{os.getpid()}"
            if old.exists():
                shutil.rmtree(old)
            os.replace(final, old)
        os.replace(tmp, final)
        if old:
            shutil.rmtree(old, ignore_errors=True)
    except Exception:
        shutil.rmtree(tmp, ignore_errors=True)
        raise


def remove_site(slug: str | None) -> None:
    if slug:
        shutil.rmtree(_site_dir(slug), ignore_errors=True)


def refresh_live_site(store: Store, db: Session) -> None:
    """Re-renders a live store after a change (catalogue, branding, info)."""
    if store.status == StoreStatusEnum.published and store.slug:
        db.flush()
        db.expire(store, ["items", "categories"])
        _write_site(store, db)


def publish(store: Store, user: User, db: Session) -> Store:
    if store.status == StoreStatusEnum.suspended:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "This store has been suspended. Please contact MePage support.")
    issues = readiness(store, db)
    if issues:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, {"message": "Your store isn't ready to publish yet.", "issues": issues})
    try:
        slugs.validate_slug(store.slug)
    except slugs.SlugError as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, {"message": str(exc), "issues": [{"step": "business", "message": str(exc)}]})
    if slugs.is_taken(store.slug, db, exclude_store_id=store.id):
        raise HTTPException(status.HTTP_409_CONFLICT, {"message": "That store address was just taken. Please choose another.",
                                                         "suggestions": slugs.suggest_alternatives(store.slug, db, store.id)})
    first = store.first_published_at is None
    store.status = StoreStatusEnum.published
    store.published_at = _now()
    if first:
        store.first_published_at = store.published_at
    store.onboarding_step = "done"
    try:
        db.flush()
    except IntegrityError:
        db.rollback()
        raise HTTPException(status.HTTP_409_CONFLICT, "That store address was just taken. Please choose another.")
    _write_site(store, db)
    audit(db, user.id, "qr.store.published", store_id=store.id, slug=store.slug, first=first)
    db.commit()
    db.refresh(store)
    return store


def unpublish(store: Store, actor: User, db: Session, reason: str = "owner") -> Store:
    remove_site(store.slug)
    if store.status == StoreStatusEnum.published:
        store.status = StoreStatusEnum.unpublished
    audit(db, actor.id, "qr.store.unpublished", store_id=store.id, slug=store.slug, reason=reason)
    db.commit()
    db.refresh(store)
    return store


def site_json(store_html: str) -> dict:
    """Extracts the embedded store JSON from rendered HTML (tests/diagnostics)."""
    start = store_html.index('id="store-data">') + len('id="store-data">')
    end = store_html.index("</script>", start)
    return json.loads(store_html[start:end])
