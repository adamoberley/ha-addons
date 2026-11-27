"""Fit an artwork to the TV panel and encode JPEG.

Museum art is all aspect ratios; the Frame is 16:9. Two modes:
  matte (default) - the whole work shown, centered on a coloured mat with a
                    small border, like a framed print. Nothing is cropped.
  crop            - scale to cover the panel and center-crop the overflow.
"""
from __future__ import annotations

from io import BytesIO

from PIL import Image


def _rgb(hex_color: str) -> tuple:
    h = (hex_color or "#141414").lstrip("#")
    if len(h) != 6:
        h = "141414"
    try:
        return int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)
    except ValueError:
        return 20, 20, 20


def decodes(image_bytes: bytes) -> bool:
    """True if the bytes are a whole, decodable image.

    A source can serve a damaged file with a 200 - reframed.gallery's CDN has
    at least one original cut off before its JPEG end marker - and Pillow only
    notices when it decodes every row, so check before committing to a piece
    rather than failing the whole change at render time."""
    try:
        with Image.open(BytesIO(image_bytes)) as img:
            img.load()
        return True
    except Exception:          # any decode failure means "not usable"
        return False


def fit_to_panel(image_bytes: bytes, width: int, height: int,
                 mode: str = "matte", mat_color: str = "#141414",
                 quality: int = 90) -> bytes:
    with Image.open(BytesIO(image_bytes)) as src:
        img = src.convert("RGB")

        if mode == "crop":
            sr, dr = img.width / img.height, width / height
            if sr > dr:
                nh = height
                nw = round(nh * sr)
            else:
                nw = width
                nh = round(nw / sr)
            img = img.resize((nw, nh), Image.LANCZOS)
            left, top = (nw - width) // 2, (nh - height) // 2
            out = img.crop((left, top, left + width, top + height))
        else:  # matte: contain on a mat canvas, with a small border
            canvas = Image.new("RGB", (width, height), _rgb(mat_color))
            scale = min(width / img.width, height / img.height) * 0.92
            nw = max(1, round(img.width * scale))
            nh = max(1, round(img.height * scale))
            img = img.resize((nw, nh), Image.LANCZOS)
            canvas.paste(img, ((width - nw) // 2, (height - nh) // 2))
            out = canvas

        buf = BytesIO()
        out.save(buf, format="JPEG", quality=quality)
        return buf.getvalue()
