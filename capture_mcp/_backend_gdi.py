"""GDI BitBlt backend — direct ctypes, no dependencies beyond stdlib + Pillow.

Captures by HWND (specific window) or full desktop.
More flexible than pyautogui: can grab off-screen/minimized windows via PrintWindow.
"""
from __future__ import annotations
import ctypes
import ctypes.wintypes as wt
import io, base64
from PIL import Image

NAME = "gdi"

_gdi32  = ctypes.windll.gdi32
_user32 = ctypes.windll.user32

# GDI constants
SRCCOPY     = 0x00CC0020
DIB_RGB_COLORS = 0

class _BITMAPINFOHEADER(ctypes.Structure):
    _fields_ = [
        ("biSize",          ctypes.c_uint32),
        ("biWidth",         ctypes.c_int32),
        ("biHeight",        ctypes.c_int32),
        ("biPlanes",        ctypes.c_uint16),
        ("biBitCount",      ctypes.c_uint16),
        ("biCompression",   ctypes.c_uint32),
        ("biSizeImage",     ctypes.c_uint32),
        ("biXPelsPerMeter", ctypes.c_int32),
        ("biYPelsPerMeter", ctypes.c_int32),
        ("biClrUsed",       ctypes.c_uint32),
        ("biClrImportant",  ctypes.c_uint32),
    ]

def available() -> bool:
    try:
        _user32.GetDesktopWindow()
        return True
    except Exception:
        return False

def _screen_size() -> tuple[int, int]:
    return (_user32.GetSystemMetrics(0), _user32.GetSystemMetrics(1))

def capture(x: int = 0, y: int = 0, w: int | None = None, h: int | None = None) -> bytes:
    sw, sh = _screen_size()
    cw = w or sw
    ch = h or sh

    hwnd   = _user32.GetDesktopWindow()
    hdc    = _user32.GetDC(hwnd)
    hdc_m  = _gdi32.CreateCompatibleDC(hdc)
    hbmp   = _gdi32.CreateCompatibleBitmap(hdc, cw, ch)
    _gdi32.SelectObject(hdc_m, hbmp)
    _gdi32.BitBlt(hdc_m, 0, 0, cw, ch, hdc, x, y, SRCCOPY)

    bmi = _BITMAPINFOHEADER()
    bmi.biSize     = ctypes.sizeof(_BITMAPINFOHEADER)
    bmi.biWidth    = cw
    bmi.biHeight   = -ch   # negative = top-down
    bmi.biPlanes   = 1
    bmi.biBitCount = 32

    buf = (ctypes.c_char * (cw * ch * 4))()
    _gdi32.GetDIBits(hdc_m, hbmp, 0, ch, buf, ctypes.byref(bmi), DIB_RGB_COLORS)

    _gdi32.DeleteObject(hbmp)
    _gdi32.DeleteDC(hdc_m)
    _user32.ReleaseDC(hwnd, hdc)

    img = Image.frombuffer("RGBA", (cw, ch), buf, "raw", "BGRA", 0, 1).convert("RGB")
    out = io.BytesIO()
    img.save(out, format="PNG")
    return out.getvalue()

def capture_b64(x: int = 0, y: int = 0, w: int | None = None, h: int | None = None) -> str:
    return base64.b64encode(capture(x, y, w, h)).decode()
