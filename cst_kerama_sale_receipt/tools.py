"""Helpers shared by every 80 mm receipt (sales check, kassa check)."""
import base64
import functools
import io
import logging

from PIL import Image, ImageOps

from odoo.tools import formatLang
from odoo.tools.misc import file_open

_logger = logging.getLogger(__name__)

# 80 mm paper at 203 dpi prints ~576 dots; more pixels only make the page heavier.
_LOGO_MAX_WIDTH = 576


def receipt_money(env, amount):
    """Receipt-friendly number: grouped, and only as many decimals as needed.

    A whole value prints without the ``.00`` noise; a genuinely fractional
    amount still shows its decimals so ``qty x price = subtotal`` adds up.
    """
    amount = amount or 0.0
    digits = 0 if float(amount).is_integer() else 2
    return formatLang(env, amount, digits=digits)


@functools.lru_cache(maxsize=1)
def _placeholder_logo():
    with file_open("base/static/img/res_company_logo.png", "rb") as f:
        return f.read()


@functools.lru_cache(maxsize=16)
def _receipt_logo_uri(data):
    """Trim the white margin, go grayscale for the thermal head, return a data URI."""
    img = ImageOps.exif_transpose(Image.open(io.BytesIO(data)))
    if img.mode in ("RGBA", "LA", "P"):
        img = img.convert("RGBA")
        flat = Image.new("RGBA", img.size, (255, 255, 255, 255))
        flat.alpha_composite(img)
        img = flat
    gray = img.convert("L")
    # a square logo with a small wordmark in the middle would waste paper
    bbox = gray.point(lambda p: 255 if p < 240 else 0).getbbox()
    if bbox:
        pad = max(2, int(min(gray.size) * 0.01))
        left, top, right, bottom = bbox
        gray = gray.crop((max(left - pad, 0), max(top - pad, 0),
                          min(right + pad, gray.width), min(bottom + pad, gray.height)))
    gray = ImageOps.autocontrast(gray)
    if gray.width > _LOGO_MAX_WIDTH:
        height = max(1, round(gray.height * _LOGO_MAX_WIDTH / gray.width))
        gray = gray.resize((_LOGO_MAX_WIDTH, height), Image.LANCZOS)
    out = io.BytesIO()
    gray.save(out, "PNG", optimize=True)
    return "data:image/png;base64," + base64.b64encode(out.getvalue()).decode()


def receipt_logo(company):
    """Company logo ready for the receipt, or False (no logo / Odoo's "Your logo")."""
    raw = company.sudo().logo
    if not raw:
        return False
    try:
        data = base64.b64decode(raw)
        if data == _placeholder_logo():
            return False
        return _receipt_logo_uri(data)
    except Exception:  # a broken image must never stop a receipt from printing
        _logger.warning("Receipt logo of company %s could not be processed", company.id, exc_info=True)
        return False
