"""MSS screenshot backend — fast GDI via python-mss."""
from __future__ import annotations
import io, base64
from PIL import Image

NAME = "mss"

def available() -> bool:
    try:
        import mss
        return True
    except Exception:
        return False

def capture(x: int = 0, y: int = 0, w: int | None = None, h: int | None = None) -> bytes:
    """Return PNG bytes."""
    import mss, mss.tools
    with mss.MSS() as sct:
        mon = sct.monitors[1]  # primary monitor
        region = {
            "left":   x if w else mon["left"],
            "top":    y if h else mon["top"],
            "width":  w if w else mon["width"],
            "height": h if h else mon["height"],
        }
        shot = sct.grab(region)
        img = Image.frombytes("RGB", shot.size, shot.bgra, "raw", "BGRX")
        buf = io.BytesIO()
        img.save(buf, format="PNG")
        return buf.getvalue()

def capture_b64(x: int = 0, y: int = 0, w: int | None = None, h: int | None = None) -> str:
    return base64.b64encode(capture(x, y, w, h)).decode()
