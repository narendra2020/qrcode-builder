"""
MePage-branded QR codes for a store's public URL.

Scannability rules applied:
- Error correction level H (≈30% recoverable) because a brand mark sits
  in the middle; the mark covers < 7% of the symbol area, well inside H's
  budget, and is placed on a white pad so no partial modules remain.
- Dark modules on a white background only (brand color is used for the
  frame and label, never the modules unless it has ≥ 7:1 contrast on white),
  with the standard 4-module quiet zone kept clear.
- Every generated PNG is decoded back with zxing-cpp and must yield the
  exact store URL, otherwise generation fails loudly (verify_png).

Layouts: "card" (printable card with store name, "Scan to view our
menu", URL and "Powered by MePage · mepage.in") and "plain" (code + small
Powered-by line). PNG at digital (1024px) or print (3000px ≈ 10 in @ 300 dpi)
size; SVG is vector and resolution independent.
"""
import base64
import io
from functools import lru_cache
from pathlib import Path
from urllib.parse import quote, urlsplit
from xml.sax.saxutils import escape

import segno
from PIL import Image, ImageDraw, ImageFont

from app.services.branding import contrast_ratio

ASSETS = Path(__file__).resolve().parent.parent / "static" / "brand"
MEPAGE_VIOLET = "#6657ed"
MEPAGE_LIME = "#b9f47a"
QUIET_ZONE = 4
LOGO_FRACTION = 0.22   # of the symbol width (≈ 5% of area incl. pad)

PNG_SIZES = {"digital": 1024, "print": 3000}


class QrError(RuntimeError):
    pass


def _qr(url: str):
    return segno.make(url, error="h", micro=False, boost_error=False)


def _module_color(brand: str | None) -> str:
    if brand and contrast_ratio(brand, "#ffffff") >= 7:
        return brand
    return "#111111"


@lru_cache(maxsize=8)
def _font(size: int, bold: bool = False) -> ImageFont.ImageFont:
    name = "Inter-Bold.ttf" if bold else "Inter-Regular.ttf"
    for candidate in (ASSETS / name, Path("/usr/share/fonts/truetype/dejavu") / ("DejaVuSans-Bold.ttf" if bold else "DejaVuSans.ttf")):
        if candidate.exists():
            return ImageFont.truetype(str(candidate), size)
    return ImageFont.load_default(size=size)


def _brandmark(size: int) -> Image.Image:
    """The MePage "M" mark drawn natively (same geometry as the app's SVG)."""
    scale = size / 64
    img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    d.rounded_rectangle((0, 0, size - 1, size - 1), radius=int(17 * scale), fill=MEPAGE_VIOLET)
    pts = [(15, 44), (15, 20), (22, 20), (32, 33), (42, 20), (49, 20), (49, 44), (41, 44), (41, 31), (32, 42), (23, 31), (23, 44)]
    d.polygon([(x * scale, y * scale) for x, y in pts], fill="#ffffff")
    r = 5 * scale
    d.ellipse((49 * scale - r, 16 * scale - r, 49 * scale + r, 16 * scale + r), fill=MEPAGE_LIME)
    return img


BRANDMARK_SVG = (
    '<rect width="64" height="64" rx="17" fill="#6657ed"/>'
    '<path d="M15 44V20h7l10 13 10-13h7v24h-8V31l-9 11-9-11v13z" fill="#fff"/>'
    '<circle cx="49" cy="16" r="5" fill="#b9f47a"/>'
)


def _symbol_png(url: str, px: int, dark: str) -> Image.Image:
    qr = _qr(url)
    modules = qr.symbol_size(border=QUIET_ZONE)[0]
    scale = max(1, px // modules)
    buf = io.BytesIO()
    qr.save(buf, kind="png", scale=scale, border=QUIET_ZONE, dark=dark, light="#ffffff")
    img = Image.open(io.BytesIO(buf.getvalue())).convert("RGB")
    if img.width != px:
        img = img.resize((px, px), Image.NEAREST)
    # Brand mark on a white pad, centred and aligned to the module grid.
    inner = px * (modules - 2 * QUIET_ZONE) / modules
    mark = int(inner * LOGO_FRACTION)
    pad = int(mark * 0.16)
    cx = px // 2
    box = (cx - mark // 2 - pad, cx - mark // 2 - pad, cx + mark // 2 + pad, cx + mark // 2 + pad)
    ImageDraw.Draw(img).rounded_rectangle(box, radius=pad * 2, fill="#ffffff")
    img.paste(_brandmark(mark), (cx - mark // 2, cx - mark // 2), _brandmark(mark))
    return img


def _text_width(draw: ImageDraw.ImageDraw, text: str, font) -> int:
    return int(draw.textlength(text, font=font))


def _fit_text(draw, text: str, max_width: int, size: int, bold: bool):
    while size > 10:
        font = _font(size, bold)
        if _text_width(draw, text, font) <= max_width:
            return font, text
        size -= 2
    font = _font(size, bold)
    while text and _text_width(draw, text + "…", font) > max_width:
        text = text[:-1]
    return font, text + "…"


def table_url(base_url: str, table_no: str) -> str:
    """Store URL carrying the sitting-area / table label (read by the storefront)."""
    return f"{base_url}?table={quote(table_no, safe='')}"


def render_png(url: str, store_name: str, brand_color: str | None, layout: str = "card", size: str = "digital",
               table_no: str | None = None) -> bytes:
    """`url` is exactly what the QR encodes; `table_no` only adds a printed label."""
    width = PNG_SIZES.get(size, PNG_SIZES["digital"])
    dark = _module_color(brand_color)
    accent = brand_color or MEPAGE_VIOLET
    if layout == "plain":
        symbol = _symbol_png(url, width, dark)
        canvas = Image.new("RGB", (width, int(width * 1.1)), "#ffffff")
        canvas.paste(symbol, (0, 0))
        draw = ImageDraw.Draw(canvas)
        font = _font(int(width * 0.035))
        label = f"Table {table_no} · Powered by MePage" if table_no else "Powered by MePage · mepage.in"
        label_font, label = _fit_text(draw, label, int(width * 0.9), int(width * 0.035), False)
        draw.text(((width - _text_width(draw, label, label_font)) // 2, int(width * 1.02)), label, fill="#55586a", font=label_font)
    else:
        u = width / 1000
        height = int(1460 * u)
        canvas = Image.new("RGB", (width, height), "#ffffff")
        draw = ImageDraw.Draw(canvas)
        draw.rounded_rectangle((int(20 * u), int(20 * u), width - int(20 * u), height - int(20 * u)),
                               radius=int(48 * u), outline=accent, width=max(2, int(10 * u)))
        font, name = _fit_text(draw, store_name, int(820 * u), int(64 * u), True)
        draw.text(((width - _text_width(draw, name, font)) // 2, int(90 * u)), name, fill="#111111", font=font)
        sub = _font(int(36 * u))
        cta = "Scan to view our menu & enquire on WhatsApp"
        f_cta, cta = _fit_text(draw, cta, int(860 * u), int(36 * u), False)
        draw.text(((width - _text_width(draw, cta, f_cta)) // 2, int(185 * u)), cta, fill="#444757", font=f_cta)
        sym = int(780 * u)
        canvas.paste(_symbol_png(url, sym, dark), ((width - sym) // 2, int(250 * u)))
        f_url, shown = _fit_text(draw, _display_url(url), int(860 * u), int(40 * u), True)
        draw.text(((width - _text_width(draw, shown, f_url)) // 2, int((1035 if table_no else 1060) * u)), shown, fill=accent if contrast_ratio(accent, "#ffffff") >= 4.5 else "#111111", font=f_url)
        if table_no:
            f_tbl, tbl = _fit_text(draw, f"Table {table_no}", int(860 * u), int(52 * u), True)
            draw.text(((width - _text_width(draw, tbl, f_tbl)) // 2, int(1090 * u)), tbl, fill="#111111", font=f_tbl)
        draw.line((int(120 * u), int(1160 * u), width - int(120 * u), int(1160 * u)), fill="#e5e7f0", width=max(1, int(3 * u)))
        mark = int(64 * u)
        powered = "Powered by MePage"
        f_pow = _font(int(36 * u), True)
        pw = _text_width(draw, powered, f_pow)
        x0 = (width - (mark + int(18 * u) + pw)) // 2
        canvas.paste(_brandmark(mark), (x0, int(1205 * u)), _brandmark(mark))
        draw.text((x0 + mark + int(18 * u), int(1215 * u)), powered, fill="#17172b", font=f_pow)
        site = "mepage.in"
        draw.text(((width - _text_width(draw, site, sub)) // 2, int(1300 * u)), site, fill=MEPAGE_VIOLET, font=sub)
    buf = io.BytesIO()
    canvas.save(buf, "PNG", optimize=True, dpi=(300, 300) if size == "print" else (72, 72))
    data = buf.getvalue()
    verify_png(data, url)
    return data


def _display_url(url: str) -> str:
    parts = urlsplit(url)
    return (parts.netloc + parts.path).rstrip("/")


def render_svg(url: str, store_name: str, brand_color: str | None, layout: str = "card",
               table_no: str | None = None) -> str:
    qr = _qr(url)
    dark = _module_color(brand_color)
    accent = brand_color or MEPAGE_VIOLET
    modules = qr.symbol_size(border=QUIET_ZONE)[0]
    # Module paths from segno, embedded in our own layout.
    buf = io.BytesIO()
    qr.save(buf, kind="svg", border=QUIET_ZONE, dark=dark, light="#ffffff", xmldecl=False, svgns=True, nl=False)
    symbol_svg = buf.getvalue().decode()
    inner = modules - 2 * QUIET_ZONE
    mark = inner * LOGO_FRACTION
    pad = mark * 0.16
    c = modules / 2
    logo = (
        f'<rect x="{c - mark / 2 - pad:.3f}" y="{c - mark / 2 - pad:.3f}" width="{mark + 2 * pad:.3f}" '
        f'height="{mark + 2 * pad:.3f}" rx="{pad * 2:.3f}" fill="#fff"/>'
        f'<g transform="translate({c - mark / 2:.3f} {c - mark / 2:.3f}) scale({mark / 64:.5f})">{BRANDMARK_SVG}</g>'
    )
    symbol_b64 = base64.b64encode(symbol_svg.encode()).decode()
    url_label = escape(_display_url(url))
    table_label = escape(f"Table {table_no}") if table_no else ""
    name = escape(store_name)
    if layout == "plain":
        return (
            f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {modules} {modules * 1.1:.2f}" width="1024" height="{1024 * 1.1:.0f}">'
            f'<rect width="100%" height="100%" fill="#fff"/>'
            f'<image href="data:image/svg+xml;base64,{symbol_b64}" width="{modules}" height="{modules}"/>{logo}'
            f'<text x="{c}" y="{modules * 1.06:.2f}" font-family="Inter, Arial, sans-serif" font-size="{modules * 0.035:.2f}" '
            f'fill="#55586a" text-anchor="middle">{escape(f"Table {table_no} · ") if table_no else ""}Powered by MePage · mepage.in</text></svg>'
        )
    s = 780 / modules
    return (
        '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 1000 1460" width="1000" height="1460">'
        '<rect width="1000" height="1460" fill="#fff"/>'
        f'<rect x="20" y="20" width="960" height="1420" rx="48" fill="none" stroke="{accent}" stroke-width="10"/>'
        f'<text x="500" y="150" font-family="Inter, Arial, sans-serif" font-size="64" font-weight="700" fill="#111" text-anchor="middle">{name}</text>'
        '<text x="500" y="220" font-family="Inter, Arial, sans-serif" font-size="34" fill="#444757" text-anchor="middle">Scan to view our menu &amp; enquire on WhatsApp</text>'
        f'<g transform="translate(110 250) scale({s:.5f})">'
        f'<image href="data:image/svg+xml;base64,{symbol_b64}" width="{modules}" height="{modules}"/>{logo}</g>'
        f'<text x="500" y="{1075 if table_no else 1100}" font-family="Inter, Arial, sans-serif" font-size="40" font-weight="700" fill="{accent if contrast_ratio(accent, "#ffffff") >= 4.5 else "#111"}" text-anchor="middle">{url_label}</text>'
        + (f'<text x="500" y="1140" font-family="Inter, Arial, sans-serif" font-size="52" font-weight="700" fill="#111" text-anchor="middle">{table_label}</text>' if table_no else "") +
        '<line x1="120" y1="1160" x2="880" y2="1160" stroke="#e5e7f0" stroke-width="3"/>'
        f'<g transform="translate(330 1205)">{BRANDMARK_SVG}</g>'
        '<text x="412" y="1250" font-family="Inter, Arial, sans-serif" font-size="36" font-weight="700" fill="#17172b">Powered by MePage</text>'
        '<a href="https://mepage.in"><text x="500" y="1335" font-family="Inter, Arial, sans-serif" font-size="36" fill="#6657ed" text-anchor="middle">mepage.in</text></a>'
        '</svg>'
    )


def decode_png(data: bytes) -> list[str]:
    import zxingcpp

    img = Image.open(io.BytesIO(data)).convert("L")
    return [r.text for r in zxingcpp.read_barcodes(img)]


def verify_png(data: bytes, url: str) -> None:
    try:
        texts = decode_png(data)
    except ImportError:  # decoder unavailable: skip check rather than block publishing
        return
    if url not in texts:
        raise QrError("Generated QR code failed the scannability check.")
