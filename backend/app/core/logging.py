"""
Structured JSON logging with per-request correlation IDs.

Never log OTPs, tokens, signed-URL query strings, uploaded image bytes or
customer message contents — log identifiers and outcomes only.
"""
import contextvars
import json
import logging
import re
import sys

request_id_var: contextvars.ContextVar[str] = contextvars.ContextVar("request_id", default="-")
# Admin id when the request is made through a ghost (impersonation) token; stamped on every audit event.
impersonator_var: contextvars.ContextVar[str | None] = contextvars.ContextVar("impersonator", default=None)

_REQUEST_ID_RE = re.compile(r"^[A-Za-z0-9-]{8,64}$")


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload = {
            "ts": self.formatTime(record, "%Y-%m-%dT%H:%M:%S%z"),
            "level": record.levelname,
            "logger": record.name,
            "msg": record.getMessage(),
            "request_id": request_id_var.get(),
        }
        fields = getattr(record, "fields", None)
        if fields:
            payload.update(fields)
        if record.exc_info:
            payload["exc"] = self.formatException(record.exc_info)
        return json.dumps(payload, default=str)


def configure_logging(level: int = logging.INFO) -> None:
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(JsonFormatter())
    root = logging.getLogger("qr")
    root.handlers = [handler]
    root.setLevel(level)
    root.propagate = False


def get_logger(name: str) -> logging.Logger:
    return logging.getLogger(f"qr.{name}")


def log_event(logger: logging.Logger, msg: str, level: int = logging.INFO, **fields) -> None:
    logger.log(level, msg, extra={"fields": fields})


def accept_request_id(raw: str | None) -> str | None:
    return raw if raw and _REQUEST_ID_RE.match(raw) else None
