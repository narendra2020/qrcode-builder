"""
Phone normalization, price formatting and WhatsApp click-to-chat links.

The storefront builds the same messages client-side
(app/templates/storefront/_store.js) — keep the two in sync; the shared
fixtures in tests/test_whatsapp.py pin the exact format.
"""
import re
from decimal import ROUND_HALF_UP, Decimal
from urllib.parse import quote

# Conservative ceiling for the full https://wa.me/... URL. Long prefilled
# texts are truncated or dropped by some WhatsApp clients/browsers well
# before the HTTP URL limit.
MAX_WA_URL_LENGTH = 2000

CURRENCY_SYMBOLS = {"INR": "₹", "USD": "$", "EUR": "€", "GBP": "£", "AED": "AED ", "SGD": "S$"}


class PhoneError(ValueError):
    pass


def normalize_phone(raw: str, default_country_code: str = "91") -> str:
    """
    Returns E.164 (+<digits>). Accepts "+<cc><number>", "00<cc><number>",
    or a 10-digit Indian mobile (6-9 prefix), with any spacing/punctuation.
    """
    raw = (raw or "").strip()
    has_plus = raw.startswith("+")
    digits = re.sub(r"\D", "", raw)
    if not has_plus and digits.startswith("00"):
        digits, has_plus = digits[2:], True
    if not has_plus:
        if len(digits) == 11 and digits.startswith("0"):
            digits = digits[1:]
        if len(digits) == 10:
            if default_country_code == "91" and digits[0] not in "6789":
                raise PhoneError("Enter a valid 10-digit mobile number.")
            digits = default_country_code + digits
        elif len(digits) == 12 and digits.startswith("91"):
            pass
        else:
            raise PhoneError("Include your country code, e.g. +91 98765 43210.")
    if not 8 <= len(digits) <= 15 or digits.startswith("0"):
        raise PhoneError("Enter a valid phone number with country code.")
    if digits.startswith("91") and (len(digits) != 12 or digits[2] not in "6789"):
        raise PhoneError("Enter a valid 10-digit Indian mobile number.")
    return "+" + digits


def _indian_grouping(int_part: str) -> str:
    if len(int_part) <= 3:
        return int_part
    head, tail = int_part[:-3], int_part[-3:]
    groups = []
    while len(head) > 2:
        groups.insert(0, head[-2:])
        head = head[:-2]
    if head:
        groups.insert(0, head)
    return ",".join(groups) + "," + tail


def format_price(amount: Decimal | float | int | None, currency: str = "INR") -> str | None:
    """₹1,25,000 / ₹250 / ₹99.50 — Indian digit grouping for INR."""
    if amount is None:
        return None
    value = Decimal(str(amount)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    negative = value < 0
    value = abs(value)
    int_part, frac = f"{value:.2f}".split(".")
    grouped = _indian_grouping(int_part) if currency == "INR" else f"{int(int_part):,}"
    text = grouped if frac == "00" else f"{grouped}.{frac}"
    symbol = CURRENCY_SYMBOLS.get(currency, f"{currency} ")
    return f"{'-' if negative else ''}{symbol}{text}"


def item_price_label(price: Decimal | None, price_text: str | None, currency: str) -> str | None:
    """The owner-facing price string: exact price if known, else the verbatim
    price text (e.g. "₹250 / ₹400"), else None."""
    if price is not None:
        return format_price(price, currency)
    return price_text or None


def wa_link(phone_e164: str, message: str) -> str:
    return f"https://wa.me/{phone_e164.lstrip('+')}?text={quote(message, safe='')}"


def _table_line(table_no: str | None) -> str:
    return f"Table: {table_no}\n\n" if table_no else ""


def item_enquiry_message(store_name: str, store_url: str, item_name: str, price_label: str | None,
                         table_no: str | None = None) -> str:
    line = f"- {item_name} — {price_label}" if price_label else f"- {item_name} (price not listed)"
    return (
        f"Hello {store_name},\n\n{_table_line(table_no)}"
        f"I would like to enquire about:\n{line}\n\n"
        f"Store: {store_url}\n\n"
        f"Please share more details."
    )


def cart_enquiry_message(
    store_name: str, store_url: str, lines: list[dict], currency: str, include_lines: int | None = None,
    table_no: str | None = None,
) -> str:
    """
    lines: [{"name", "qty", "price": Decimal|None, "price_text": str|None}].
    A subtotal is shown only when every line has an exact price, and is
    labelled as an estimate the store must confirm.
    """
    shown = lines if include_lines is None else lines[:include_lines]
    body = []
    for idx, line in enumerate(shown, start=1):
        label = item_price_label(line.get("price"), line.get("price_text"), currency)
        price_part = f"{label} each" if line.get("price") is not None else (label or "Price unavailable")
        body.append(f"{idx}. {line['name']} — Qty: {line['qty']} — {price_part}")
    hidden = len(lines) - len(shown)
    if hidden > 0:
        body.append(f"…and {hidden} more item(s) — I'll share the full list in chat.")

    msg = f"Hello {store_name},\n\n{_table_line(table_no)}I would like to enquire about the following items:\n\n" + "\n".join(body)
    if hidden == 0 and lines and all(line.get("price") is not None for line in lines):
        subtotal = sum(Decimal(str(line["price"])) * int(line["qty"]) for line in lines)
        msg += f"\n\nEstimated subtotal: {format_price(subtotal, currency)} (to be confirmed by the store)"
    msg += f"\n\nStore: {store_url}\n\nPlease confirm availability and the final total."
    return msg


def build_cart_link(store_name: str, store_url: str, phone: str, lines: list[dict], currency: str,
                    table_no: str | None = None) -> dict:
    """Returns {"url", "truncated", "included"}; shortens the list until the
    link fits MAX_WA_URL_LENGTH."""
    message = cart_enquiry_message(store_name, store_url, lines, currency, table_no=table_no)
    url = wa_link(phone, message)
    if len(url) <= MAX_WA_URL_LENGTH:
        return {"url": url, "truncated": False, "included": len(lines)}
    for keep in range(len(lines) - 1, 0, -1):
        message = cart_enquiry_message(store_name, store_url, lines, currency, include_lines=keep, table_no=table_no)
        url = wa_link(phone, message)
        if len(url) <= MAX_WA_URL_LENGTH:
            return {"url": url, "truncated": True, "included": keep}
    message = cart_enquiry_message(store_name, store_url, lines, currency, include_lines=0, table_no=table_no)
    return {"url": wa_link(phone, message), "truncated": True, "included": 0}


def split_bill_message(*, name: str | None, store_name: str, total_label: str, people: int, share_label: str,
                       upi_id: str | None, upi_link: str | None, qr_url: str | None) -> str:
    """Per-participant split-bill text (used for click-to-chat; the Cloud API
    path sends the same facts through an approved template)."""
    lines = [
        f"Hi {name}," if name else "Hi,", "",
        f"You have been invited to split a bill at {store_name}.", "",
        "Bill details:",
        f"- Restaurant: {store_name}",
        f"- Total bill: {total_label}",
        f"- Number of people: {people}",
        f"- Your share: {share_label}", "",
        "Payment details:",
    ]
    if upi_id:
        lines.append(f"UPI ID: {upi_id}")
    if upi_link:
        lines.append(f"Pay {share_label} in your UPI app: {upi_link}")
    if qr_url:
        lines.append(f"Payment QR code: {qr_url}")
    if not upi_link and qr_url:
        lines.append(f"If you scan the QR code, enter {share_label} before paying.")
    lines += ["", f"Please pay {share_label}. This message does not confirm payment.", "", "Thank you!"]
    return "\n".join(lines)
