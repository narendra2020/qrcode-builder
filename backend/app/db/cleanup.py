"""
Retention: deletes uploaded menu/catalogue source photos
SOURCE_IMAGE_RETENTION_DAYS after a store's first publish (extraction is
finished by then and the structured catalogue is what's kept), plus
soft-deleted media and orphaned item images. Run daily from cron:

    python -m app.db.cleanup
"""
from datetime import datetime, timedelta, timezone

from app.core.config import settings
from app.db.session import SessionLocal
from app.models.models import CatalogueItem, Media, MediaKindEnum, Store
from app.services import media as media_service


def run() -> dict:
    db = SessionLocal()
    removed_sources = removed_orphans = 0
    try:
        if settings.SOURCE_IMAGE_RETENTION_DAYS > 0:
            cutoff = datetime.now(timezone.utc) - timedelta(days=settings.SOURCE_IMAGE_RETENTION_DAYS)
            rows = (
                db.query(Media).join(Store, Media.store_id == Store.id)
                .filter(Media.kind == MediaKindEnum.source, Store.first_published_at.isnot(None),
                        Store.first_published_at < cutoff)
                .all()
            )
            for media in rows:
                media_service.delete_files(media)
                db.delete(media)
                removed_sources += 1

        # A week's grace so images in unsaved editor drafts aren't removed.
        day_ago = datetime.now(timezone.utc) - timedelta(days=7)
        used = db.query(CatalogueItem.image_media_id).filter(CatalogueItem.image_media_id.isnot(None))
        branding_ids = {v for (b,) in db.query(Store.branding).all() for k, v in (b or {}).items() if k.endswith("_media_id") and v}
        orphans = (
            db.query(Media)
            .filter(Media.kind != MediaKindEnum.source, Media.created_at < day_ago, ~Media.id.in_(used))
            .all()
        )
        for media in orphans:
            if media.id in branding_ids:
                continue
            media_service.delete_files(media)
            db.delete(media)
            removed_orphans += 1
        db.commit()
    finally:
        db.close()
    result = {"sources_removed": removed_sources, "orphans_removed": removed_orphans}
    print(f"[qr-cleanup] {result}")
    return result


if __name__ == "__main__":
    run()
