"""
WhatsApp Business Cloud API sender for Split Bill invitations.

Business-initiated WhatsApp messages must use a pre-approved TEMPLATE (see
README → "Split Bill → WhatsApp setup" for the exact body). When the
template/credentials aren't configured, callers fall back to click-to-chat
links, so this module is entirely optional.

Credentials never leave the backend. Participant phone numbers are not logged.
"""
from dataclasses import dataclass

import httpx

from app.core.config import settings
from app.core.logging import get_logger

logger = get_logger("whatsapp_cloud")

_TIMEOUT = httpx.Timeout(10.0, connect=5.0)


def delivery_mode() -> str:
    return "cloud_api" if settings.whatsapp_cloud_enabled else "manual"


@dataclass
class SendResult:
    ok: bool
    message_id: str | None = None
    error: str | None = None
    retryable: bool = False


def _param(value: str) -> dict:
    # Template parameters can't contain newlines/tabs or long runs of spaces.
    return {"type": "text", "text": " ".join(str(value).split())[:1000] or "-"}


def send_split_bill(to_e164: str, body_params: list[str], header_image_url: str | None = None) -> SendResult:
    """body_params fill {{1}}..{{n}} of the approved template, in order."""
    if not settings.whatsapp_cloud_enabled:
        return SendResult(False, error="WhatsApp sending is not configured.")
    components: list[dict] = []
    if header_image_url and settings.WHATSAPP_SPLIT_BILL_IMAGE_HEADER:
        components.append({"type": "header", "parameters": [{"type": "image", "image": {"link": header_image_url}}]})
    components.append({"type": "body", "parameters": [_param(p) for p in body_params]})
    payload = {
        "messaging_product": "whatsapp",
        "to": to_e164.lstrip("+"),
        "type": "template",
        "template": {
            "name": settings.WHATSAPP_SPLIT_BILL_TEMPLATE,
            "language": {"code": settings.WHATSAPP_SPLIT_BILL_TEMPLATE_LANG},
            "components": components,
        },
    }
    url = f"https://graph.facebook.com/{settings.WHATSAPP_API_VERSION}/{settings.WHATSAPP_PHONE_NUMBER_ID}/messages"
    try:
        with httpx.Client(timeout=_TIMEOUT) as client:
            res = client.post(url, json=payload, headers={"Authorization": f"Bearer {settings.WHATSAPP_ACCESS_TOKEN}"})
    except httpx.HTTPError as exc:
        logger.warning("whatsapp send transport error: %s", type(exc).__name__)
        return SendResult(False, error="Could not reach WhatsApp. Please retry.", retryable=True)

    if res.status_code < 400:
        try:
            mid = res.json()["messages"][0]["id"]
        except (ValueError, KeyError, IndexError, TypeError):
            mid = None
        return SendResult(True, message_id=mid)

    code, detail = None, ""
    try:
        err = res.json().get("error", {})
        code, detail = err.get("code"), str(err.get("message", ""))[:150]
    except ValueError:
        pass
    logger.warning("whatsapp send rejected: status=%s code=%s", res.status_code, code)
    retryable = res.status_code >= 500 or res.status_code == 429 or code in (4, 80007, 130429, 131056)
    if code in (131026, 131030, 1013):
        friendly = "This number isn't on WhatsApp or can't receive the message."
    else:
        friendly = "WhatsApp couldn't deliver the message."
    return SendResult(False, error=f"{friendly}{f' ({code})' if code else ''}", retryable=retryable)
