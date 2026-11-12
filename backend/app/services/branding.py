"""
Store branding: validated colors, controlled fonts, logo/banner media and
a computed, contrast-safe theme used by every storefront template.
"""
import re

from app.catalog.registry import FONTS, TEMPLATE_BY_KEY

HEX_RE = re.compile(r"^#[0-9a-fA-F]{6}$")
COLOR_KEYS = ("primary", "secondary", "background", "text")

FALLBACK = {"primary": "#6657ed", "secondary": "#b9f47a", "background": "#ffffff", "text": "#17172b", "font": "Inter"}


class BrandingError(ValueError):
    pass


def _rgb(hex_color: str) -> tuple[float, float, float]:
    h = hex_color.lstrip("#")
    return tuple(int(h[i:i + 2], 16) / 255 for i in (0, 2, 4))  # type: ignore[return-value]


def _luminance(hex_color: str) -> float:
    def channel(c: float) -> float:
        return c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4
    r, g, b = (channel(c) for c in _rgb(hex_color))
    return 0.2126 * r + 0.7152 * g + 0.0722 * b


def contrast_ratio(a: str, b: str) -> float:
    la, lb = sorted((_luminance(a), _luminance(b)), reverse=True)
    return (la + 0.05) / (lb + 0.05)


def readable_on(bg: str) -> str:
    """Black or white, whichever reads better on `bg`."""
    return "#ffffff" if contrast_ratio(bg, "#ffffff") >= contrast_ratio(bg, "#111111") else "#111111"


def defaults_for(template_key: str | None) -> dict:
    template = TEMPLATE_BY_KEY.get(template_key or "")
    return {**FALLBACK, **(template.defaults if template else {})}


def validate_branding(data: dict) -> dict:
    """Validates an owner-submitted branding update (partial)."""
    out: dict = {}
    for key in COLOR_KEYS:
        if key in data and data[key] is not None:
            value = str(data[key]).strip()
            if not HEX_RE.match(value):
                raise BrandingError(f"{key.capitalize()} color must be a hex value like #1f6feb.")
            out[key] = value.lower()
    if data.get("font") is not None:
        if data["font"] not in FONTS:
            raise BrandingError("Choose one of the available fonts.")
        out["font"] = data["font"]
    for key in ("logo_media_id", "banner_media_id"):
        if key in data:
            out[key] = data[key] or None
    return out


def theme(branding: dict, template_key: str | None) -> dict:
    """Effective theme: owner overrides on top of the template defaults,
    with text colour auto-corrected when it fails WCAG AA on the background."""
    merged = {**defaults_for(template_key), **{k: v for k, v in (branding or {}).items() if v}}
    warnings = []
    if contrast_ratio(merged["text"], merged["background"]) < 4.5:
        merged["text"] = readable_on(merged["background"])
        warnings.append("Text color was adjusted for readability on your background.")
    font = merged.get("font") if merged.get("font") in FONTS else "Inter"
    spec, stack = FONTS[font]
    return {
        **{k: merged[k] for k in COLOR_KEYS},
        "on_primary": readable_on(merged["primary"]),
        "on_secondary": readable_on(merged["secondary"]),
        "font": font,
        "font_spec": spec,
        "font_stack": stack,
        "warnings": warnings,
    }
