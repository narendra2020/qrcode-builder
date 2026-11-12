"""
MePage QR Store Builder API.

Runs alongside portfolio-builder (same database, same JWT secret, same
auth endpoints). Run locally with:
    uvicorn app.main:app --reload --port 8002
"""
import time
import uuid

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from sqlalchemy import text
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.ai.jobs import recover_stale_jobs
from app.api.routes import admin, public, split_bill, stores
from app.core.config import settings
from app.core.security import decode_token
from app.core.logging import accept_request_id, configure_logging, get_logger, log_event, request_id_var, impersonator_var
from app.db.session import SessionLocal

configure_logging()
logger = get_logger("http")

app = FastAPI(
    title="MePage QR Store Builder API",
    description="AI-assisted digital storefronts with branded QR codes and WhatsApp enquiries.",
    version="1.0.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=False,
    allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE"],
    allow_headers=["Authorization", "Content-Type", "X-Request-ID", "X-Split-Token"],
)


def _ghost_admin(request: Request) -> str | None:
    auth = request.headers.get("authorization", "")
    if not auth.lower().startswith("bearer "):
        return None
    try:
        return decode_token(auth[7:].strip()).get("imp")
    except ValueError:
        return None


@app.middleware("http")
async def request_context(request: Request, call_next):
    request_id = accept_request_id(request.headers.get("x-request-id")) or uuid.uuid4().hex
    token = request_id_var.set(request_id)
    imp_token = impersonator_var.set(_ghost_admin(request))
    started = time.perf_counter()
    try:
        response = await call_next(request)
    except Exception:
        logger.exception("unhandled error")
        response = JSONResponse({"detail": "Something went wrong. Please try again.", "request_id": request_id},
                                status_code=500)
    finally:
        request_id_var.reset(token)
        impersonator_var.reset(imp_token)
    response.headers["X-Request-ID"] = request_id
    response.headers.setdefault("X-Content-Type-Options", "nosniff")
    response.headers.setdefault("Referrer-Policy", "strict-origin-when-cross-origin")
    if not request.url.path.endswith("/preview"):
        response.headers.setdefault("X-Frame-Options", "DENY")
    log_event(logger, "request", method=request.method, path=request.url.path, status=response.status_code,
              ms=round((time.perf_counter() - started) * 1000, 1), request_id=request_id)
    return response


@app.exception_handler(RequestValidationError)
async def validation_handler(request: Request, exc: RequestValidationError):
    # Field paths + messages only — never echo submitted values back.
    errors = [{"field": ".".join(str(p) for p in e["loc"][1:]), "message": e["msg"]} for e in exc.errors()]
    return JSONResponse({"detail": {"message": "Some fields are invalid.", "errors": errors}}, status_code=422)


@app.exception_handler(StarletteHTTPException)
async def http_handler(request: Request, exc: StarletteHTTPException):
    return JSONResponse({"detail": exc.detail}, status_code=exc.status_code, headers=getattr(exc, "headers", None))


app.include_router(stores.router)
app.include_router(public.router)
app.include_router(split_bill.owner_router)
app.include_router(split_bill.public_router)
app.include_router(admin.router)


@app.on_event("startup")
def _startup() -> None:
    try:
        recover_stale_jobs()
    except Exception:
        logger.exception("stale job recovery failed")


@app.get("/api/qr/health", tags=["health"])
def health():
    db = SessionLocal()
    try:
        db.execute(text("SELECT 1"))
        database = "ok"
    except Exception:
        database = "error"
    finally:
        db.close()
    return JSONResponse({"status": "ok" if database == "ok" else "degraded", "service": "qr-store-builder", "database": database},
                        status_code=200 if database == "ok" else 503)
