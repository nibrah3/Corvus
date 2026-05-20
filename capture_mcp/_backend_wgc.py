"""Windows.Graphics.Capture (WGC) backend.

Modern Windows 10 1903+ hardware-accelerated capture.
Can grab specific windows by HWND even if occluded.
Uses winsdk Python package (Windows Runtime bindings).

Install: pip install winsdk
"""
from __future__ import annotations
import io, base64, asyncio, ctypes
from PIL import Image

NAME = "wgc"

def available() -> bool:
    try:
        import winsdk.windows.graphics.capture as wgc          # noqa: F401
        import winsdk.windows.graphics.directx.direct3d11 as d3  # noqa: F401
        return True
    except Exception:
        return False

# ── Helpers ───────────────────────────────────────────────────────────────────

def _primary_hwnd() -> int:
    """Return HWND of the desktop shell window (entire screen)."""
    user32 = ctypes.windll.user32
    return user32.GetDesktopWindow()

def _get_monitor_size() -> tuple[int, int]:
    user32 = ctypes.windll.user32
    return user32.GetSystemMetrics(0), user32.GetSystemMetrics(1)

# ── Core async capture ────────────────────────────────────────────────────────

async def _capture_async(x: int, y: int, w: int | None, h: int | None) -> bytes:
    """
    WGC capture pipeline:
    1. Create IDirect3D11CaptureFramePool
    2. Create GraphicsCaptureSession for display/window
    3. Grab one frame → SoftwareBitmap → PIL Image
    """
    import winsdk.windows.graphics.capture as wgc
    import winsdk.windows.graphics.directx as gd
    import winsdk.windows.graphics.directx.direct3d11 as d3d
    import winsdk.windows.graphics.imaging as wgi
    import winsdk.windows.foundation as wf

    sw, sh = _get_monitor_size()
    cw = w or sw
    ch = h or sh

    # Get capture item for the primary display
    interop = wgc.GraphicsCaptureItem._obj.QueryInterface(
        wgc.IGraphicsCaptureItemInterop
    ) if hasattr(wgc, 'IGraphicsCaptureItemInterop') else None

    # Simpler path: use CreateForMonitor via display item
    # This requires Windows 10 1903+
    displays = await wgc.GraphicsCaptureItem.create_for_monitor_async(None)
    frame_pool = wgc.Direct3D11CaptureFramePool.create(
        d3d.Direct3D11Device(),
        gd.DirectXPixelFormat.B8_G8_R8_A8_UINT_NORMALIZED,
        1,
        wgc.SizeInt32(cw, ch),
    )
    session = frame_pool.create_capture_session(displays)
    session.start_capture()

    import asyncio
    frame = None
    for _ in range(10):
        frame = frame_pool.try_get_next_frame()
        if frame:
            break
        await asyncio.sleep(0.02)

    session.close()
    frame_pool.close()

    if frame is None:
        raise RuntimeError("WGC: no frame captured")

    # Convert to SoftwareBitmap → bytes
    bitmap = await wgi.SoftwareBitmap.create_copy_from_surface_async(frame.surface)
    bitmap = wgi.SoftwareBitmap.convert(bitmap, wgi.BitmapPixelFormat.BGRA8, wgi.BitmapAlphaMode.PREMULTIPLIED)

    buf_ref = wgi.BitmapBuffer(None)
    encoder = await wgi.BitmapEncoder.create_async(wgi.BitmapEncoder.png_encoder_id, io.BytesIO())
    encoder.set_software_bitmap(bitmap)
    await encoder.flush_async()
    return bytes(encoder)


def capture(x: int = 0, y: int = 0, w: int | None = None, h: int | None = None) -> bytes:
    """Synchronous wrapper — runs async pipeline in new event loop."""
    try:
        loop = asyncio.get_event_loop()
        if loop.is_running():
            import concurrent.futures
            with concurrent.futures.ThreadPoolExecutor(1) as ex:
                fut = ex.submit(asyncio.run, _capture_async(x, y, w, h))
                return fut.result(timeout=5)
        return loop.run_until_complete(_capture_async(x, y, w, h))
    except Exception as exc:
        raise RuntimeError(f"WGC capture failed: {exc}") from exc


def capture_b64(x: int = 0, y: int = 0, w: int | None = None, h: int | None = None) -> str:
    return base64.b64encode(capture(x, y, w, h)).decode()
