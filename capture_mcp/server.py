"""
Capture MCP server.

Tools:
  screenshot        — full screen or region, returns base64 PNG/JPEG
  screenshot_region — convenience wrapper for a named region
  start_video       — begin DXcam continuous capture (for Gemini video pipeline)
  stop_video        — stop capture, save MP4, return file path

Backend priority: MSS (single-shot) + DXcam (video/continuous)
GDI as fallback if MSS fails.
"""
from __future__ import annotations

import base64, io, os, time
from typing import Optional

from _minmcp import MinMCP

from ._backend_mss import capture as _mss_cap, available as _mss_ok
from ._backend_gdi import capture as _gdi_cap, available as _gdi_ok
from ._backend_dxcam import available as _dxcam_ok

mcp = MinMCP("capture")

# ── Single-shot backend selection ─────────────────────────────────────────────

def _screenshot_bytes(
    x: int = 0, y: int = 0,
    w: Optional[int] = None, h: Optional[int] = None,
    fmt: str = "jpeg", quality: int = 72,
) -> tuple[bytes, str]:
    """
    Returns (image_bytes, mime_type).
    Tries MSS first, falls back to GDI.
    fmt: 'jpeg' (smaller, faster) or 'png' (lossless).
    """
    from PIL import Image

    if _mss_ok():
        img = _mss_cap(x, y, w, h)
        pil = Image.open(io.BytesIO(img))
    elif _gdi_ok():
        img = _gdi_cap(x, y, w, h)
        pil = Image.open(io.BytesIO(img))
    else:
        raise RuntimeError("No screenshot backend available")

    # Crop centre 60% width (removes taskbar/sidebars Claude ignores)
    # Only apply when full-screen (no region specified)
    if w is None and h is None and fmt == "jpeg":
        pw, ph = pil.size
        margin = int(pw * 0.20)
        pil = pil.crop((margin, 0, pw - margin, ph))

    buf = io.BytesIO()
    if fmt == "jpeg":
        pil.save(buf, format="JPEG", quality=quality, optimize=True)
        mime = "image/jpeg"
    else:
        pil.save(buf, format="PNG")
        mime = "image/png"

    return buf.getvalue(), mime


# ── DXcam video state ─────────────────────────────────────────────────────────

_video_cam    = None
_video_frames = []
_video_active = False


# ── Tools ─────────────────────────────────────────────────────────────────────

@mcp.tool()
def screenshot(
    x: int = 0,
    y: int = 0,
    width: Optional[int] = None,
    height: Optional[int] = None,
    format: str = "jpeg",
    quality: int = 72,
) -> dict:
    """
    Capture the screen and return a base64-encoded image for Claude vision.

    Default (no args): captures full screen, crops centre 60% width, JPEG 72%.
    This is Pipeline F — fastest single-shot with best token efficiency.

    Args:
        x, y:         Top-left of capture region (default 0,0 = full screen).
        width, height: Region size. Omit for full screen.
        format:        "jpeg" (default, smaller) or "png" (lossless).
        quality:       JPEG quality 1-95 (default 72).

    Returns:
        {base64: str, mime_type: str, width: int, height: int, size_kb: float}
    """
    t0 = time.perf_counter()
    data, mime = _screenshot_bytes(x, y, width, height, format, quality)
    ms = (time.perf_counter() - t0) * 1000

    from PIL import Image
    img = Image.open(io.BytesIO(data))
    w, h = img.size

    return {
        "base64":   base64.standard_b64encode(data).decode(),
        "mime_type": mime,
        "width":    w,
        "height":   h,
        "size_kb":  round(len(data) / 1024, 1),
        "capture_ms": round(ms, 1),
    }


@mcp.tool()
def screenshot_region(
    region: str,
    format: str = "jpeg",
) -> dict:
    """
    Capture a named region of the screen.

    Regions:
        "left_half"    — left 50% of screen
        "right_half"   — right 50%
        "top_half"     — top 50%
        "bottom_half"  — bottom 50%
        "center"       — centre 60% width, full height (same as Pipeline F default)
        "fullscreen"   — full screen, no crop, PNG

    Useful for multi-monitor setups or when content is in a known area.
    """
    import ctypes
    sw = ctypes.windll.user32.GetSystemMetrics(0)
    sh = ctypes.windll.user32.GetSystemMetrics(1)

    regions = {
        "left_half":   (0,      0, sw//2, sh),
        "right_half":  (sw//2,  0, sw//2, sh),
        "top_half":    (0,      0, sw,    sh//2),
        "bottom_half": (0,   sh//2, sw,   sh//2),
        "center":      (int(sw*0.20), 0, int(sw*0.60), sh),
        "fullscreen":  (0,      0, sw,    sh),
    }

    coords = regions.get(region.lower())
    if coords is None:
        raise ValueError(f"Unknown region '{region}'. Valid: {list(regions)}")

    x, y, w, h = coords
    fmt = "png" if region == "fullscreen" else format
    return screenshot(x=x, y=y, width=w, height=h, format=fmt)


@mcp.tool()
def start_video_capture(fps: int = 30) -> str:
    """
    Start continuous DXcam screen recording for the Gemini video pipeline.

    Use this before a video assessment begins, then call stop_video_capture()
    when the video ends to get the recorded file path.

    Args:
        fps: Target frames per second (default 30).

    Returns: "started" or error message.
    """
    global _video_cam, _video_frames, _video_active

    if not _dxcam_ok():
        return "ERROR: dxcam not available — install with: pip install dxcam"

    if _video_active:
        return "already recording"

    import dxcam
    _video_cam = dxcam.create(output_color="BGR")
    _video_frames = []
    _video_active = True

    import threading

    def _record():
        _video_cam.start(target_fps=fps)
        while _video_active:
            frame = _video_cam.get_latest_frame()
            if frame is not None:
                _video_frames.append(frame)
            time.sleep(1 / fps)
        _video_cam.stop()

    threading.Thread(target=_record, daemon=True).start()
    return f"started at {fps}fps"


@mcp.tool()
def stop_video_capture(output_path: str = "D:/cb-core/capture_mcp/recording.mp4") -> str:
    """
    Stop recording and save frames as MP4.

    Returns: absolute path to the saved MP4 file, ready for Gemini Video API.
    """
    global _video_active, _video_frames, _video_cam

    if not _video_active:
        return "ERROR: not recording"

    _video_active = False
    time.sleep(0.5)  # let recording thread stop

    frames = list(_video_frames)
    _video_frames = []

    if not frames:
        return "ERROR: no frames captured"

    import cv2
    import numpy as np

    h, w = frames[0].shape[:2]
    fourcc = cv2.VideoWriter_fourcc(*"mp4v")
    out = cv2.VideoWriter(output_path, fourcc, 30, (w, h))
    for f in frames:
        out.write(f)
    out.release()

    return output_path


if __name__ == "__main__":
    mcp.run()
