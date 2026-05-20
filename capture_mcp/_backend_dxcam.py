"""DXcam backend — GPU DXGI framebuffer capture."""
from __future__ import annotations
import io, base64
from PIL import Image

NAME = "dxcam"

_cam = None

def available() -> bool:
    try:
        import dxcam
        return True
    except Exception:
        return False

def _get_cam():
    global _cam
    if _cam is None:
        import dxcam
        _cam = dxcam.create(output_color="BGR")
    return _cam

def _screen_size() -> tuple[int, int]:
    import ctypes
    user32 = ctypes.windll.user32
    user32.SetProcessDPIAware()
    return user32.GetSystemMetrics(0), user32.GetSystemMetrics(1)

def capture(x: int = 0, y: int = 0, w: int | None = None, h: int | None = None) -> bytes:
    """Return PNG bytes. DXcam returns numpy BGR array."""
    cam = _get_cam()
    sw, sh = _screen_size()
    if w and h:
        x2 = min(x + w, sw)
        y2 = min(y + h, sh)
        region = (max(x, 0), max(y, 0), x2, y2)
        frame = cam.grab(region=region)
    else:
        frame = cam.grab()

    if frame is None:
        # DXcam returns None if frame unchanged since last grab — retry once
        import time
        time.sleep(0.02)
        region = (max(x, 0), max(y, 0), min(x+w, sw), min(y+h, sh)) if w and h else None
        frame = cam.grab(region=region)
    if frame is None:
        raise RuntimeError("dxcam returned None frame")

    # frame is BGR numpy — convert to RGB PIL
    import numpy as np
    img = Image.fromarray(frame[:, :, ::-1])  # BGR → RGB
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()

def capture_b64(x: int = 0, y: int = 0, w: int | None = None, h: int | None = None) -> str:
    return base64.b64encode(capture(x, y, w, h)).decode()
