"""
Audit events, written to portfolio-builder's shared audit_logs table with
a "qr." action prefix so platform admins see one history. Only ids and
outcomes go in `meta` — never phone numbers, OTPs or message contents.
"""
from sqlalchemy.orm import Session

from app.core.logging import get_logger, impersonator_var, log_event, request_id_var
from app.models.models import AuditLog

logger = get_logger("audit")


def audit(db: Session, actor_id: str | None, action: str, **meta) -> None:
    meta = {k: v for k, v in meta.items() if v is not None}
    meta["request_id"] = request_id_var.get()
    if impersonator_var.get():
        meta["impersonated_by"] = impersonator_var.get()
    db.add(AuditLog(actor_id=actor_id, action=action, meta=meta))
    log_event(logger, action, actor_id=actor_id, **meta)
