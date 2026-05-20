# capture.py — Capture Layer (Phase 2)
# SCHEMA_VERSION: 1
#
# Single responsibility: acquire raw pixel frames from the GPU framebuffer.
#
# Outputs: CaptureFrame — numpy BGRA array + metadata.
# MUST NOT: interpret pixels, run OCR, detect changes, make decisions.
#
# Backend: DXcam (Desktop Duplication API, GPU-backed, BGRA native).
# Fallback: mss (CPU screenshot, cross-platform) if DXcam unavailable.
# Public API is identical regardless of backend — callers never know which runs.

from __future__ import annotations

import time
import warnings
from contextlib import contextmanager
from dataclasses import dataclass, field
from enum import Enum
from typing import Iterator, Optional

import numpy as np
import pygetwindow as gw

from .errors import CaptureError, ErrorCode
from .schema import BoundingBox

# ── Backend detection ─────────────────────────────────────────────────────────

try:
    import dxcam as _dxcam
    _DXCAM_AVAILABLE = True
except Exception:
    _DXCAM_AVAILABLE = False

try:
    import mss as _mss
    _MSS_AVAILABLE = True
except Exception:
    _MSS_AVAILABLE = False


class CaptureBackend(Enum):
    DXCAM = "dxcam"
    MSS   = "mss"


def _available_backend() -> CaptureBackend:
    if _DXCAM_AVAILABLE:
        return CaptureBackend.DXCAM
    if _MSS_AVAILABLE:
        return CaptureBackend.MSS
    raise CaptureError(
        ErrorCode.CAPTURE_INIT_FAILED,
        "No capture backend available. Install dxcam (pip install dxcam) or mss (pip install mss).",
    )


# ── CaptureFrame ──────────────────────────────────────────────────────────────

@dataclass
class CaptureFrame:
    """
    Raw pixel frame from one capture.

    data:        numpy array, shape (h, w, 4), dtype uint8, BGRA channel order.
    frame_id:    monotonically increasing integer within a CaptureSession.
    timestamp:   time.monotonic() at moment of capture.
    window_title: title of the targeted window.
    window_bbox:  bounding box of the full window on screen.
    region:       sub-region captured (None = full window).
    backend:      which backend produced this frame.
    """
    frame_id:     int
    timestamp:    float
    data:         np.ndarray   # (h, w, 4) BGRA uint8
    window_title: str
    window_bbox:  BoundingBox
    region:       Optional[BoundingBox]
    backend:      CaptureBackend

    def __post_init__(self) -> None:
        if self.frame_id < 0:
            raise ValueError(f"CaptureFrame.frame_id must be >= 0, got {self.frame_id}")
        if self.timestamp <= 0:
            raise ValueError(f"CaptureFrame.timestamp must be > 0, got {self.timestamp}")
        if self.data.ndim != 3 or self.data.shape[2] != 4:
            raise ValueError(
                f"CaptureFrame.data must have shape (h, w, 4), got {self.data.shape}"
            )
        if self.data.dtype != np.uint8:
            raise ValueError(
                f"CaptureFrame.data must be uint8, got {self.data.dtype}"
            )

    @property
    def width(self) -> int:
        return int(self.data.shape[1])

    @property
    def height(self) -> int:
        return int(self.data.shape[0])

    @property
    def active_bbox(self) -> BoundingBox:
        """The bounding box actually captured — region if set, else window_bbox."""
        return self.region if self.region is not None else self.window_bbox


# ── Window resolution ─────────────────────────────────────────────────────────

def _find_window(title: str) -> gw.Win32Window:
    """
    Return first window whose title contains `title` (case-insensitive).
    Raises CaptureError if not found.
    """
    matches = [w for w in gw.getAllWindows() if title.lower() in w.title.lower()]
    if not matches:
        raise CaptureError(
            ErrorCode.CAPTURE_WINDOW_NOT_FOUND,
            f"No window found matching title substring: {title!r}",
            {"title": title},
        )
    return matches[0]


def _window_bbox(win: gw.Win32Window) -> BoundingBox:
    """Convert pygetwindow window geometry to BoundingBox."""
    w = max(1, win.width)
    h = max(1, win.height)
    return BoundingBox(x=win.left, y=win.top, w=w, h=h)


def _resolve_region(
    window_bbox: BoundingBox,
    region: Optional[BoundingBox],
) -> BoundingBox:
    """
    Resolve the capture region.
    If region is None, return window_bbox.
    If region is given, clamp it to window_bbox bounds and return.
    Region coordinates are absolute screen pixels (same reference frame as window_bbox).
    """
    if region is None:
        return window_bbox

    # Clamp region to window bounds
    x1 = max(window_bbox.x, region.x)
    y1 = max(window_bbox.y, region.y)
    x2 = min(window_bbox.x + window_bbox.w, region.x + region.w)
    y2 = min(window_bbox.y + window_bbox.h, region.y + region.h)

    if x2 <= x1 or y2 <= y1:
        raise CaptureError(
            ErrorCode.CAPTURE_FRAME_TIMEOUT,
            f"Requested region {region} does not intersect window {window_bbox}",
            {"region": (region.x, region.y, region.w, region.h),
             "window": (window_bbox.x, window_bbox.y, window_bbox.w, window_bbox.h)},
        )

    return BoundingBox(x=x1, y=y1, w=x2 - x1, h=y2 - y1)


# ── DXcam backend ─────────────────────────────────────────────────────────────

class _DXCamBackend:
    def __init__(self) -> None:
        try:
            self._cam = _dxcam.create(output_color="BGRA")
        except Exception as e:
            raise CaptureError(
                ErrorCode.CAPTURE_INIT_FAILED,
                f"DXcam failed to initialise: {e}",
            ) from e
        self._last_frame: Optional[np.ndarray] = None

    def grab(self, region: BoundingBox) -> np.ndarray:
        """Grab one frame for the given screen region. Returns BGRA uint8 array."""
        # Clamp to screen bounds — pygetwindow reports window chrome coords that
        # can be slightly negative (Windows shadow) or exceed screen dimensions.
        sw, sh = self._cam.width, self._cam.height
        x1 = max(0, region.x)
        y1 = max(0, region.y)
        x2 = min(sw, region.x + region.w)
        y2 = min(sh, region.y + region.h)
        if x2 <= x1 or y2 <= y1:
            raise CaptureError(
                ErrorCode.CAPTURE_FRAME_TIMEOUT,
                f"Region {region} is entirely outside screen ({sw}x{sh})",
            )
        rect = (x1, y1, x2, y2)
        # DXcam returns None when the framebuffer hasn't changed since the last
        # grab (Desktop Duplication API doesn't re-deliver the same frame).
        # Try once; if None, return the cached last frame (screen is static).
        # Only raise if we have no cached frame at all (first grab on dead screen).
        raw = self._cam.grab(region=rect)
        if raw is not None:
            self._last_frame = np.array(raw, dtype=np.uint8)
        elif self._last_frame is None:
            raise CaptureError(
                ErrorCode.CAPTURE_FRAME_TIMEOUT,
                "DXcam returned no frame and no previous frame cached "
                "(screen may be off or locked)",
            )
        return self._last_frame

    def close(self) -> None:
        try:
            self._cam.release()
        except Exception:
            # Suppress known comtypes __del__ access-violation on Python 3.14
            pass


# ── MSS backend (fallback) ────────────────────────────────────────────────────

class _MSSBackend:
    def __init__(self) -> None:
        if not _MSS_AVAILABLE:
            raise CaptureError(
                ErrorCode.CAPTURE_INIT_FAILED,
                "mss is not installed. Run: pip install mss",
            )
        self._sct = _mss.mss()

    def grab(self, region: BoundingBox) -> np.ndarray:
        monitor = {
            "left": region.x, "top": region.y,
            "width": region.w, "height": region.h,
        }
        raw = self._sct.grab(monitor)
        # mss returns BGRA natively
        return np.array(raw, dtype=np.uint8)

    def close(self) -> None:
        try:
            self._sct.close()
        except Exception:
            pass


# ── CaptureSession ────────────────────────────────────────────────────────────

class CaptureSession:
    """
    Manages the capture backend lifecycle across multiple grabs.

    Use as a context manager:
        with CaptureSession() as session:
            frame = session.grab("IXBrowser")

    Or manually:
        session = CaptureSession()
        frame = session.grab("IXBrowser")
        session.close()

    Keeping the session open across grabs is more efficient than creating
    a new camera per capture (DXcam initialisation has ~50ms overhead).
    """

    def __init__(self, backend: Optional[CaptureBackend] = None) -> None:
        chosen = backend or _available_backend()
        if chosen == CaptureBackend.DXCAM:
            self._backend = _DXCamBackend()
            self._backend_type = CaptureBackend.DXCAM
        else:
            self._backend = _MSSBackend()
            self._backend_type = CaptureBackend.MSS
        self._frame_counter: int = 0
        self._closed: bool = False

    def grab(
        self,
        title: str,
        region: Optional[BoundingBox] = None,
    ) -> CaptureFrame:
        """
        Capture one frame from window matching `title`.

        Args:
            title:  Window title substring (case-insensitive match).
            region: Optional sub-region in absolute screen pixels.
                    None = capture the full window.

        Returns:
            CaptureFrame with raw BGRA array and metadata.

        Raises:
            CaptureError if window not found or capture fails.
        """
        if self._closed:
            raise CaptureError(
                ErrorCode.CAPTURE_INIT_FAILED,
                "CaptureSession has been closed",
            )

        win = _find_window(title)
        win_bbox = _window_bbox(win)
        active_region = _resolve_region(win_bbox, region)

        ts = time.monotonic()
        data = self._backend.grab(active_region)

        frame_id = self._frame_counter
        self._frame_counter += 1

        return CaptureFrame(
            frame_id=frame_id,
            timestamp=ts,
            data=data,
            window_title=win.title,
            window_bbox=win_bbox,
            region=region,
            backend=self._backend_type,
        )

    def close(self) -> None:
        if not self._closed:
            self._backend.close()
            self._closed = True

    def __enter__(self) -> "CaptureSession":
        return self

    def __exit__(self, *_) -> None:
        self.close()


# ── Convenience one-shot capture ──────────────────────────────────────────────

def grab_once(
    title: str,
    region: Optional[BoundingBox] = None,
    backend: Optional[CaptureBackend] = None,
) -> CaptureFrame:
    """
    One-shot capture without keeping a session open.
    Slightly higher overhead than CaptureSession.grab() due to backend init.
    Suitable for single captures; use CaptureSession for repeated grabs.
    """
    with CaptureSession(backend=backend) as session:
        return session.grab(title, region)
