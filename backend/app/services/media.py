"""
Image upload validation and storage.

Every upload is validated by decoding it with Pillow (not by extension or
the client's Content-Type), size/pixel limited, EXIF-orientation fixed,
and RE-ENCODED — which strips metadata (GPS etc.) and any appended
payload. Files are stored under UPLOADS_DIR/qr/<store_id>/ with random
names and are never served statically; see app/api/routes/media.py.
"""
import hashlib
import io
import os
import uuid
from pathlib import Path

from PIL import Image, ImageOps, UnidentifiedImageError
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.security import sign_media_path
from app.models.models import Media, MediaKindEnum

Image.MAX_IMAGE_PIXELS = 50_000_000  # decompression-bomb guard

# MPO is how Pillow identifies multi-picture JPEGs written by many phone cameras.
ALLOWED_FORMATS = {"JPEG": "image/jpeg", "MPO": "image/jpeg", "PNG": "image/png", "WEBP": "image/webp"}
ALLOWED_EXTENSIONS = {"jpg", "jpeg", "png", "webp"}

# Longest edge kept for the stored original, per kind.
MAX_EDGE = {
    MediaKindEnum.source: 2400,     # enough resolution for OCR of dense menus
    MediaKindEnum.logo: 800,
    MediaKindEnum.banner: 2000,
    MediaKindEnum.item_image: 1600,
    MediaKindEnum.payment_qr: 1200,
}
VARIANT_WIDTHS = {
    MediaKindEnum.source: (),
    MediaKindEnum.logo: (160, 320),
    MediaKindEnum.banner: (800, 1600),
    MediaKindEnum.item_image: (320, 640, 1024),
    MediaKindEnum.payment_qr: (),
}
MIN_EDGE = 64


class MediaError(ValueError):
    pass


def _root() -> Path:
    return Path(settings.UPLOADS_DIR) / "qr"


def abs_path(rel_path: str) -> Path:
    root = _root().resolve()
    path = (root / rel_path).resolve()
    if root not in path.parents:
        raise MediaError("Invalid media path.")
    return path


def _decode(raw: bytes) -> Image.Image:
    if not raw:
        raise MediaError("The file is empty.")
    if len(raw) > settings.MAX_UPLOAD_BYTES:
        mb = settings.MAX_UPLOAD_BYTES // (1024 * 1024)
        raise MediaError(f"Images must be {mb} MB or smaller.")
    try:
        probe = Image.open(io.BytesIO(raw))
        fmt = probe.format
        probe.verify()
        if fmt not in ALLOWED_FORMATS:
            raise MediaError("Unsupported image type. Please upload a JPG, PNG or WEBP image.")
        img = Image.open(io.BytesIO(raw))
        img.load()
    except MediaError:
        raise
    except (UnidentifiedImageError, Image.DecompressionBombError, OSError, SyntaxError, ValueError):
        raise MediaError("This file isn't a valid image. Please upload a JPG, PNG or WEBP photo.")
    img = ImageOps.exif_transpose(img)
    if min(img.size) < MIN_EDGE:
        raise MediaError("This image is too small. Please upload a clearer photo.")
    return img


def _fit(img: Image.Image, max_edge: int) -> Image.Image:
    if max(img.size) > max_edge:
        img = img.copy()
        img.thumbnail((max_edge, max_edge), Image.LANCZOS)
    return img


def _encode(img: Image.Image, kind: MediaKindEnum) -> tuple[bytes, str, str]:
    """Logos keep transparency as PNG/WebP; everything else becomes JPEG
    (sources, for maximum OCR-model compatibility) or WebP."""
    buf = io.BytesIO()
    has_alpha = img.mode in ("RGBA", "LA") or (img.mode == "P" and "transparency" in img.info)
    if kind == MediaKindEnum.payment_qr:
        # Lossless and flattened on white: lossy codecs / transparency can break scanning.
        flat = Image.new("RGB", img.size, "white")
        rgba = img.convert("RGBA")
        flat.paste(rgba, mask=rgba.split()[3])
        flat.save(buf, "PNG", optimize=True)
        return buf.getvalue(), "image/png", "png"
    if kind == MediaKindEnum.logo and has_alpha:
        img.convert("RGBA").save(buf, "PNG", optimize=True)
        return buf.getvalue(), "image/png", "png"
    rgb = img.convert("RGB")
    if kind == MediaKindEnum.source:
        rgb.save(buf, "JPEG", quality=88, optimize=True)
        return buf.getvalue(), "image/jpeg", "jpg"
    rgb.save(buf, "WEBP", quality=84, method=4)
    return buf.getvalue(), "image/webp", "webp"


def _write(rel_path: str, data: bytes) -> None:
    path = abs_path(rel_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_bytes(data)
    os.replace(tmp, path)


def save_image(
    db: Session,
    store_id: str,
    raw: bytes,
    kind: MediaKindEnum,
    origin: str = "upload",
    crop: tuple[int, int, int, int] | None = None,
    position: int = 0,
) -> Media:
    """Validates, normalizes and stores an image. `crop` is a pixel box
    (left, top, right, bottom) in the EXIF-corrected original."""
    img = _decode(raw)
    if crop:
        left, top, right, bottom = crop
        left, top = max(0, left), max(0, top)
        right, bottom = min(img.width, right), min(img.height, bottom)
        if right - left < MIN_EDGE or bottom - top < MIN_EDGE:
            raise MediaError("The selected crop area is too small.")
        img = img.crop((left, top, right, bottom))
    return _store(db, store_id, img, kind, origin, position)


def save_pil_image(db: Session, store_id: str, img: Image.Image, kind: MediaKindEnum, origin: str) -> Media:
    return _store(db, store_id, img, kind, origin, 0)


def _store(db: Session, store_id: str, img: Image.Image, kind: MediaKindEnum, origin: str, position: int) -> Media:
    img = _fit(img, MAX_EDGE[kind])
    data, mime, ext = _encode(img, kind)
    base = f"{store_id}/{kind.value}-{uuid.uuid4().hex}"
    rel_path = f"{base}.{ext}"
    _write(rel_path, data)

    variants: dict[str, str] = {}
    for width in VARIANT_WIDTHS[kind]:
        if width >= img.width:
            continue
        variant = img.copy()
        variant.thumbnail((width, width * 4), Image.LANCZOS)
        v_data, _, v_ext = _encode(variant, kind if kind == MediaKindEnum.logo else MediaKindEnum.item_image)
        v_rel = f"{base}-w{width}.{v_ext}"
        _write(v_rel, v_data)
        variants[str(width)] = v_rel

    media = Media(
        store_id=store_id, kind=kind, origin=origin, path=rel_path, mime_type=mime,
        width=img.width, height=img.height, size_bytes=len(data),
        sha256=hashlib.sha256(data).hexdigest(), variants=variants, position=position,
    )
    db.add(media)
    db.flush()
    return media


def read_bytes(media: Media) -> bytes:
    return abs_path(media.path).read_bytes()


def delete_files(media: Media) -> None:
    for rel in [media.path, *media.variants.values()]:
        try:
            abs_path(rel).unlink(missing_ok=True)
        except (OSError, MediaError):
            pass


def signed_url(media: Media | None, variant: str | None = None) -> str | None:
    """Short-lived URL for the owner dashboard (private, unpublished media)."""
    if not media or media.deleted_at:
        return None
    rel = media.variants.get(variant, media.path) if variant else media.path
    exp, sig = sign_media_path(rel)
    return f"/api/qr/media/file/{rel}?exp={exp}&sig={sig}"


def media_out(media: Media | None) -> dict | None:
    if not media or media.deleted_at:
        return None
    thumb = None
    if media.variants:
        smallest = min(media.variants, key=int)
        thumb = signed_url(media, smallest)
    return {
        "id": media.id, "kind": media.kind.value, "width": media.width, "height": media.height,
        "url": signed_url(media), "thumb_url": thumb or signed_url(media), "origin": media.origin,
    }
