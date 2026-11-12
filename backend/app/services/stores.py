"""
Store creation, business-information updates, WhatsApp-number
verification and the dashboard serializer.

WhatsApp enquiry numbers: the owner's own verified login mobile is
trusted directly. Any other number must be proven via portfolio-builder's
existing WhatsApp OTP service (POST /api/auth/number-verification/*),
which returns a short-lived signed proof token bound to the user and
number; this service only accepts the number from that token.
"""
import re
from datetime import datetime, timezone

from fastapi import HTTPException, status
from sqlalchemy.orm import Session

from app.catalog.registry import CATEGORY_BY_KEY, TEMPLATE_BY_KEY, get_category, templates_for
from app.core.config import settings
from app.core.security import decode_token
from app.models.models import Media, MediaKindEnum, Store, StoreStatusEnum, User
from app.services import branding as branding_service
from app.services import media as media_service
from app.services import slugs
from app.services.audit import audit
from app.services.whatsapp import PhoneError, normalize_phone

EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
CURRENCY_RE = re.compile(r"^[A-Z]{3}$")


def _err(field: str, message: str) -> HTTPException:
    return HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, {"field": field, "message": message})


def create_store(user: User, name: str | None, db: Session) -> Store:
    existing = db.query(Store).filter(Store.owner_id == user.id).count()
    if existing >= settings.MAX_STORES_PER_USER:
        raise HTTPException(status.HTTP_409_CONFLICT, "You already have a store. Open it from your dashboard.")
    store = Store(owner_id=user.id, name=name or None, branding={}, onboarding_step="upload")
    # The owner's own WhatsApp-verified login number is the default enquiry number.
    try:
        store.whatsapp_number = normalize_phone(user.mobile_number_encrypted)
        store.whatsapp_verified = True
    except PhoneError:
        pass
    if user.profile:
        store.email = user.profile.email
        store.city = user.profile.city
        store.country = user.profile.country
    db.add(store)
    db.flush()
    audit(db, user.id, "qr.store.created", store_id=store.id)
    db.commit()
    db.refresh(store)
    return store


def _clean_url(value: str, field: str) -> str:
    if not re.match(r"^https://[^\s<>\"']+$", value):
        raise _err(field, "Enter a full https:// link.")
    return value


# Accepted hosts (and their subdomains) for delivery-app links.
_DELIVERY_HOSTS = {
    "zomato_url": ("Zomato", ("zomato.com", "zoma.to")),
    "swiggy_url": ("Swiggy", ("swiggy.com", "swiggy.in", "swgy.in")),
}


def _clean_delivery_url(value: str, field: str) -> str:
    from urllib.parse import urlparse

    label, hosts = _DELIVERY_HOSTS[field]
    value = _clean_url(value.strip(), field)
    host = (urlparse(value).hostname or "").lower()
    if not any(host == h or host.endswith("." + h) for h in hosts):
        raise _err(field, f"Paste your {label} restaurant link (it should be from {hosts[0]}).")
    return value


def update_store(store: Store, user: User, data: dict, db: Session) -> Store:
    from app.services import publishing

    if "name" in data:
        if not data["name"]:
            raise _err("name", "Store name is required.")
        store.name = data["name"]

    if "slug" in data and data["slug"] != store.slug:
        if store.ever_published:
            raise _err("slug", "Your store address can't change after publishing, because printed QR codes point to it. Contact support if you need a change.")
        slug = (data["slug"] or "").strip().lower()
        try:
            slugs.validate_slug(slug)
        except slugs.SlugError as exc:
            raise _err("slug", str(exc))
        if slugs.is_taken(slug, db, exclude_store_id=store.id):
            raise HTTPException(status.HTTP_409_CONFLICT, {"field": "slug", "message": "That store address is already taken.",
                                                            "suggestions": slugs.suggest_alternatives(slug, db, store.id)})
        store.slug = slug

    if "category_key" in data:
        if data["category_key"] not in CATEGORY_BY_KEY:
            raise _err("category_key", "Choose one of the listed categories.")
        if data["category_key"] != store.category_key:
            store.category_key = data["category_key"]
            store.category_source = "user"
            if store.template_key is None or store.template_key not in TEMPLATE_BY_KEY:
                store.template_key = templates_for(store.category_key)[0].key

    if "template_key" in data:
        if data["template_key"] not in TEMPLATE_BY_KEY:
            raise _err("template_key", "Choose one of the listed designs.")
        store.template_key = data["template_key"]

    for key in ("tagline", "description", "address_line", "city", "state", "postal_code", "country", "opening_hours"):
        if key in data:
            setattr(store, key, data[key] or None)

    if "email" in data:
        email = data["email"] or None
        if email and not EMAIL_RE.match(email):
            raise _err("email", "Enter a valid email address.")
        store.email = email

    if "maps_url" in data:
        store.maps_url = _clean_url(data["maps_url"], "maps_url") if data["maps_url"] else None

    for key in ("zomato_url", "swiggy_url"):
        if key in data:
            value = (data[key] or "").strip()
            if value and not get_category(store.category_key).supports_delivery_links:
                raise _err(key, "Zomato and Swiggy links are for restaurants, cafés and food businesses.")
            setattr(store, key, _clean_delivery_url(value, key) if value else None)

    if "contact_phone" in data:
        try:
            store.contact_phone = normalize_phone(data["contact_phone"]) if data["contact_phone"] else None
        except PhoneError as exc:
            raise _err("contact_phone", str(exc))

    if "whatsapp_number" in data:
        if not data["whatsapp_number"]:
            raise _err("whatsapp_number", "A WhatsApp number is required to receive enquiries.")
        try:
            number = normalize_phone(data["whatsapp_number"])
        except PhoneError as exc:
            raise _err("whatsapp_number", str(exc))
        if number != store.whatsapp_number:
            if number == _owner_number(user):
                store.whatsapp_number, store.whatsapp_verified = number, True
                audit(db, user.id, "qr.store.whatsapp_changed", store_id=store.id, method="login_number")
            else:
                raise HTTPException(status.HTTP_428_PRECONDITION_REQUIRED, {
                    "field": "whatsapp_number", "code": "verification_required",
                    "message": "We'll send a code on WhatsApp to confirm you control this number.",
                })

    if "currency" in data and data["currency"]:
        currency = data["currency"].upper()
        if not CURRENCY_RE.match(currency):
            raise _err("currency", "Use a 3-letter currency code like INR.")
        store.currency = currency

    if "onboarding_step" in data and data["onboarding_step"] and not store.ever_published:
        store.onboarding_step = data["onboarding_step"]

    db.flush()
    publishing.refresh_live_site(store, db)
    db.commit()
    db.refresh(store)
    return store


def _owner_number(user: User) -> str | None:
    try:
        return normalize_phone(user.mobile_number_encrypted)
    except PhoneError:
        return None


def apply_whatsapp_proof(store: Store, user: User, token: str, db: Session) -> Store:
    from app.services import publishing

    try:
        payload = decode_token(token)
    except ValueError:
        raise _err("whatsapp_number", "This verification has expired. Please request a new code.")
    if payload.get("type") != "number_proof" or payload.get("sub") != user.id or payload.get("purpose") != "qr_whatsapp":
        raise _err("whatsapp_number", "Invalid verification. Please request a new code.")
    try:
        number = normalize_phone(payload.get("num", ""))
    except PhoneError:
        raise _err("whatsapp_number", "Invalid verification. Please request a new code.")
    store.whatsapp_number, store.whatsapp_verified = number, True
    audit(db, user.id, "qr.store.whatsapp_changed", store_id=store.id, method="otp")
    db.flush()
    publishing.refresh_live_site(store, db)
    db.commit()
    db.refresh(store)
    return store


def update_branding(store: Store, user: User, data: dict, db: Session) -> Store:
    from app.services import publishing

    if data.pop("reset", False):
        store.branding = {k: v for k, v in (store.branding or {}).items() if k in ("logo_media_id", "banner_media_id")}
    tagline = data.pop("tagline", None)
    try:
        clean = branding_service.validate_branding({k: v for k, v in data.items() if v is not None or k.endswith("_media_id")})
    except branding_service.BrandingError as exc:
        raise _err("branding", str(exc))
    for key, kind in (("logo_media_id", MediaKindEnum.logo), ("banner_media_id", MediaKindEnum.banner)):
        if clean.get(key):
            ok = db.query(Media.id).filter(Media.id == clean[key], Media.store_id == store.id,
                                           Media.kind == kind, Media.deleted_at.is_(None)).first()
            if not ok:
                raise _err(key, "Image not found.")
    store.branding = {**(store.branding or {}), **clean}
    if tagline is not None:
        store.tagline = tagline or None
    db.flush()
    publishing.refresh_live_site(store, db)
    db.commit()
    db.refresh(store)
    return store


def store_summary(store: Store) -> dict:
    category = get_category(store.category_key) if store.category_key else None
    return {
        "id": store.id, "name": store.name, "slug": store.slug, "status": store.status.value,
        "category_key": store.category_key, "category_label": category.label if category else None,
        "template_key": store.template_key, "onboarding_step": store.onboarding_step,
        "public_url": settings.public_store_url(store.slug) if store.slug else None,
        "published_at": store.published_at, "first_published_at": store.first_published_at,
    }


def store_out(store: Store, db: Session) -> dict:
    from app.ai import jobs
    from app.services import payments, plans, publishing

    media_ids = [store.branding.get("logo_media_id"), store.branding.get("banner_media_id")]
    media = {m.id: m for m in db.query(Media).filter(Media.id.in_([m for m in media_ids if m])).all()} if any(media_ids) else {}
    sources = jobs.source_pages(store.id, db)
    theme = branding_service.theme(store.branding, store.template_key)
    return {
        **store_summary(store),
        "base_domain": settings.BASE_DOMAIN,
        "category_source": store.category_source,
        "delivery_links_supported": get_category(store.category_key).supports_delivery_links,
        "suspended_reason": store.suspended_reason if store.status == StoreStatusEnum.suspended else None,
        "business": {
            "name": store.name, "tagline": store.tagline, "description": store.description,
            "address_line": store.address_line, "city": store.city, "state": store.state,
            "postal_code": store.postal_code, "country": store.country, "contact_phone": store.contact_phone,
            "whatsapp_number": store.whatsapp_number, "whatsapp_verified": store.whatsapp_verified,
            "email": store.email, "opening_hours": store.opening_hours, "maps_url": store.maps_url,
            "zomato_url": store.zomato_url, "swiggy_url": store.swiggy_url,
            "currency": store.currency,
        },
        "branding": {
            **{k: v for k, v in (store.branding or {}).items() if not k.endswith("_media_id")},
            "logo": media_service.media_out(media.get(store.branding.get("logo_media_id"))),
            "banner": media_service.media_out(media.get(store.branding.get("banner_media_id"))),
            "effective": {k: theme[k] for k in ("primary", "secondary", "background", "text", "font")},
            "warnings": theme["warnings"],
        },
        "payment": payments.payment_out(store, db),
        "sources": [media_service.media_out(m) for m in sources],
        "job": jobs.job_out(jobs.latest_job(store.id, db)),
        "item_count": len(store.items),
        "review_count": sum(1 for i in store.items if i.needs_review),
        "readiness": publishing.readiness(store, db),
        "usage": plans.usage_summary(store, db),
        "owner_number": _owner_number(store.owner),
        "now": datetime.now(timezone.utc),
    }
