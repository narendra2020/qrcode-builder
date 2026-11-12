"""
Asynchronous AI analysis jobs with explicit progress, timeouts, retries
and partial-failure recovery.

Pipeline: the owner uploads source pages -> POST /analysis creates a job
-> a worker thread analyses each page (one multimodal call per page,
retried with exponential backoff on transient errors) and stores the
normalized per-page result in job.pages. Category suggestion + business
details are aggregated into job.result. Catalogue items stay in the job
until the owner imports them (catalogue.import_from_job), so the AI runs
once per page and templates/re-imports never re-run it.

There is no queue broker in this platform, so jobs run on an in-process
ThreadPoolExecutor. Durability comes from the DB: each page result is
committed as it finishes, a heartbeat is written while running, and a job
whose heartbeat goes stale (process restart) is marked failed with a
retryable error instead of spinning forever. Retrying only re-runs the
pages that did not succeed.
"""
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone

from fastapi import HTTPException, status
from sqlalchemy.orm import Session
from sqlalchemy.orm.attributes import flag_modified

from app.ai.normalize import aggregate_business, aggregate_category, aggregate_currency, normalize_item
from app.ai.providers import AiError, get_analyzer
from app.core.config import settings
from app.core.logging import get_logger, log_event
from app.db.session import SessionLocal
from app.models.models import ExtractionJob, JobStatusEnum, Media, MediaKindEnum, Store
from app.services import media as media_service

logger = get_logger("ai.jobs")
_executor = ThreadPoolExecutor(max_workers=settings.AI_WORKERS, thread_name_prefix="qr-ai")

ACTIVE = (JobStatusEnum.queued, JobStatusEnum.running)


def _now() -> datetime:
    return datetime.now(timezone.utc)


def source_pages(store_id: str, db: Session) -> list[Media]:
    return (
        db.query(Media)
        .filter(Media.store_id == store_id, Media.kind == MediaKindEnum.source, Media.deleted_at.is_(None))
        .order_by(Media.position, Media.created_at)
        .all()
    )


def latest_job(store_id: str, db: Session) -> ExtractionJob | None:
    job = (
        db.query(ExtractionJob)
        .filter(ExtractionJob.store_id == store_id)
        .order_by(ExtractionJob.created_at.desc())
        .first()
    )
    if job:
        _expire_if_stale(job, db)
    return job


def _expire_if_stale(job: ExtractionJob, db: Session) -> None:
    if job.status not in ACTIVE:
        return
    last = job.heartbeat_at or job.started_at or job.created_at
    if last and _now() - last > timedelta(minutes=settings.AI_JOB_STALE_MINUTES):
        job.status = JobStatusEnum.failed
        job.error_code = "interrupted"
        job.error_message = "Processing was interrupted. Please retry."
        job.finished_at = _now()
        for page in job.pages:
            if page["status"] in ("queued", "running"):
                page["status"], page["error"] = "failed", "Processing was interrupted."
        flag_modified(job, "pages")
        db.commit()


def recover_stale_jobs() -> None:
    """Called at startup: anything still active belonged to a dead process."""
    db = SessionLocal()
    try:
        for job in db.query(ExtractionJob).filter(ExtractionJob.status.in_(ACTIVE)).all():
            job.heartbeat_at = datetime(2000, 1, 1, tzinfo=timezone.utc)
            _expire_if_stale(job, db)
    finally:
        db.close()


def start_job(store: Store, user_id: str, db: Session) -> ExtractionJob:
    current = latest_job(store.id, db)
    if current and current.status in ACTIVE:
        raise HTTPException(status.HTTP_409_CONFLICT, "Your photos are already being analysed.")
    pages = source_pages(store.id, db)
    if not pages:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Upload at least one photo of your menu or catalogue first.")
    job = ExtractionJob(
        store_id=store.id,
        requested_by=user_id,
        status=JobStatusEnum.queued,
        pages=[{"media_id": m.id, "status": "queued", "attempts": 0, "error": None, "item_count": 0, "result": None}
               for m in pages],
    )
    db.add(job)
    db.commit()
    _dispatch(job.id)
    return job


def retry_job(store: Store, db: Session) -> ExtractionJob:
    """Re-runs only the failed pages of the latest job, keeping succeeded ones.
    Pages added or removed since are reconciled."""
    job = latest_job(store.id, db)
    if not job:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Nothing to retry yet.")
    if job.status in ACTIVE:
        raise HTTPException(status.HTTP_409_CONFLICT, "Your photos are already being analysed.")
    current_ids = [m.id for m in source_pages(store.id, db)]
    if not current_ids:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Upload at least one photo first.")
    kept = {p["media_id"]: p for p in job.pages if p["media_id"] in current_ids and p["status"] == "succeeded"}
    job.pages = [
        kept.get(mid) or {"media_id": mid, "status": "queued", "attempts": 0, "error": None, "item_count": 0, "result": None}
        for mid in current_ids
    ]
    job.status = JobStatusEnum.queued
    job.error_code = job.error_message = None
    job.finished_at = None
    flag_modified(job, "pages")
    db.commit()
    _dispatch(job.id)
    return job


def _dispatch(job_id: str) -> None:
    if settings.AI_RUN_INLINE:
        run_job(job_id)
    else:
        _executor.submit(run_job, job_id)


def _analyze_with_retries(analyzer, image: bytes, mime: str, page: dict) -> dict:
    last_error: AiError | None = None
    for attempt in range(1, settings.AI_MAX_ATTEMPTS + 1):
        page["attempts"] = page.get("attempts", 0) + 1
        try:
            return analyzer.analyze_page(image, mime)
        except AiError as exc:
            last_error = exc
            if not exc.retryable or attempt == settings.AI_MAX_ATTEMPTS:
                break
            time.sleep(settings.AI_RETRY_BASE_SECONDS * (2 ** (attempt - 1)))
    raise last_error  # type: ignore[misc]


def _page_result(raw: dict) -> dict:
    currency_hint = (raw.get("currency") or None)
    items = []
    for raw_item in raw.get("items") or []:
        if isinstance(raw_item, dict):
            item = normalize_item(raw_item, currency_hint)
            if item:
                item["price"] = str(item["price"]) if item["price"] is not None else None
                items.append(item)
    return {
        "readable": bool(raw.get("readable", True)),
        "unreadable_reason": raw.get("unreadable_reason"),
        "category": raw.get("category") or {},
        "business": raw.get("business") or {},
        "currency": raw.get("currency"),
        "items": items[: settings.MAX_CATALOGUE_ITEMS],
    }


def run_job(job_id: str) -> None:
    db = SessionLocal()
    try:
        job = db.get(ExtractionJob, job_id)
        if not job or job.status not in ACTIVE:
            return
        try:
            analyzer = get_analyzer()
        except AiError as exc:
            _finish_failed(job, db, exc.code, exc.message)
            return
        job.status, job.started_at, job.heartbeat_at = JobStatusEnum.running, _now(), _now()
        job.provider, job.model = analyzer.provider, analyzer.model
        db.commit()
        log_event(logger, "extraction_started", job_id=job.id, store_id=job.store_id, pages=len(job.pages))

        # commit() expires `job`, so mutate a local copy and assign it back on each save.
        pages = list(job.pages)
        for page in pages:
            if page["status"] == "succeeded":
                continue
            page["status"], page["error"] = "running", None
            job.heartbeat_at = _now()
            job.pages = list(pages)
            db.commit()

            media = db.get(Media, page["media_id"])
            try:
                if not media or media.deleted_at:
                    raise AiError("missing", "This photo was removed.", retryable=False)
                raw = _analyze_with_retries(analyzer, media_service.read_bytes(media), media.mime_type, page)
                result = _page_result(raw)
                page["result"] = result
                page["item_count"] = len(result["items"])
                if not result["readable"]:
                    page["status"] = "unreadable"
                    page["error"] = result.get("unreadable_reason") or "We couldn't read a menu or price list in this photo."
                else:
                    page["status"] = "succeeded"
            except AiError as exc:
                page["status"], page["error"] = "failed", exc.message
                page["error_code"] = exc.code
                log_event(logger, "extraction_page_failed", job_id=job.id, code=exc.code, retryable=exc.retryable)
            except Exception:  # never leave the job stuck on an unexpected bug
                logger.exception("extraction page crashed", extra={"fields": {"job_id": job.id}})
                page["status"], page["error"] = "failed", "Something went wrong while reading this photo."
            job.heartbeat_at = _now()
            job.pages = list(pages)
            db.commit()

        _finalize(job, db)
    finally:
        db.close()


def _finish_failed(job: ExtractionJob, db: Session, code: str, message: str) -> None:
    job.status, job.error_code, job.error_message, job.finished_at = JobStatusEnum.failed, code, message, _now()
    for page in job.pages:
        if page["status"] in ("queued", "running"):
            page["status"], page["error"] = "failed", message
    flag_modified(job, "pages")
    db.commit()
    log_event(logger, "extraction_failed", job_id=job.id, code=code)


def _finalize(job: ExtractionJob, db: Session) -> None:
    results = [p["result"] for p in job.pages if p["status"] == "succeeded" and p.get("result")]
    failed = [p for p in job.pages if p["status"] != "succeeded"]
    if results:
        job.result = {
            "category": aggregate_category(results),
            "business": aggregate_business(results),
            "currency": aggregate_currency(results),
            "item_count": sum(len(r["items"]) for r in results),
        }
        job.status = JobStatusEnum.partial if failed else JobStatusEnum.succeeded
        job.error_code = job.error_message = None
        if failed:
            job.error_message = f"{len(failed)} of {len(job.pages)} photo(s) could not be read."
    else:
        job.result = None
        job.status = JobStatusEnum.failed
        unreadable = all(p["status"] == "unreadable" for p in job.pages)
        job.error_code = "unreadable" if unreadable else (failed[0].get("error_code") or "failed")
        job.error_message = (
            "We couldn't find a menu or product list in these photos. Try a clearer, well-lit photo."
            if unreadable else (failed[0].get("error") or "We couldn't analyse your photos.")
        )
    job.finished_at = _now()
    db.commit()
    log_event(logger, "extraction_finished", job_id=job.id, status=job.status.value,
              items=(job.result or {}).get("item_count", 0))


def job_out(job: ExtractionJob | None) -> dict | None:
    if not job:
        return None
    done = sum(1 for p in job.pages if p["status"] not in ("queued", "running"))
    return {
        "id": job.id,
        "status": job.status.value,
        "progress": {"done": done, "total": len(job.pages)},
        "pages": [
            {"media_id": p["media_id"], "status": p["status"], "error": p.get("error"), "item_count": p.get("item_count", 0)}
            for p in job.pages
        ],
        "result": job.result,
        "error_code": job.error_code,
        "error_message": job.error_message,
        "created_at": job.created_at,
        "finished_at": job.finished_at,
    }
