"""PyAutoGUI screenshot backend — GDI BitBlt via PIL."""
from __future__ import annotations
import io, base64
from PIL import Image

NAME = "pyautogui"

def available() -> bool:
    try:
        import pyautogui
        return True
    except Exception:
        return False

def capture(x: int = 0, y: int = 0, w: int | None = None, h: int | None = None) -> bytes:
    """Return PNG bytes."""
    import pyautogui
    if w and h:
        img = pyautogui.screenshot(region=(x, y, w, h))
    else:
        img = pyautogui.screenshot()
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()

def capture_b64(x: int = 0, y: int = 0, w: int | None = None, h: int | None = None) -> str:
    return base64.b64encode(capture(x, y, w, h)).decode()
