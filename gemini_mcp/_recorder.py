"""
DXcam-based screen recorder for Gemini Video analysis.

Design:
  start_recording()  → spawns background thread capturing at target_fps
  stop_recording()   → signals thread to stop, writes frames to MP4 via OpenCV

Why DXcam for video (not MSS):
  DXcam continuous mode (.start() → .get_latest_frame()) runs a GPU capture
  loop at 30-120fps. MSS's single-shot .grab() reinitialises hardware each call
  (255ms average). For video we need consistent frame intervals — DXcam excels here.

Output: H.264 MP4 compatible with Gemini File API (max 1GB, max 1 hour).
  We target 5fps at 720p — sufficient for reading UI text, much smaller files.
  A 60-second capture at 5fps = ~300 frames ≈ 20-40MB.
"""
from __future__ import annotations

import threading
import time
import os
from pathlib import Path
from typing import Optional

import numpy as np

# Lazy imports — avoid startup cost when recorder isn't used
_dxcam = None
_cv2 = None


def _ensure_deps():
    global _dxcam, _cv2
    if _dxcam is None:
        import dxcam
        _dxcam = dxcam
    if _cv2 is None:
        import cv2
        _cv2 = cv2


class _Recorder:
    def __init__(self, fps: int, region: Optional[tuple[int, int, int, int]]):
        self.fps = fps
        self.region = region  # (left, top, right, bottom) or None for full screen
        self._frames: list[np.ndarray] = []
        self._stop = threading.Event()
        self._thread: Optional[threading.Thread] = None
        self._cam = None
        self._started_at: float = 0.0

    def start(self):
        _ensure_deps()
        self._cam = _dxcam.create(output_color="BGR")
        self._cam.start(target_fps=self.fps, video_mode=True)
        self._started_at = time.monotonic()
        self._frames.clear()
        self._stop.clear()
        self._thread = threading.Thread(target=self._capture_loop, daemon=True)
        self._thread.start()

    def _capture_loop(self):
        interval = 1.0 / self.fps
        while not self._stop.is_set():
            t0 = time.monotonic()
            frame = self._cam.get_latest_frame()
            if frame is not None:
                if self.region:
                    l, t, r, b = self.region
                    frame = frame[t:b, l:r]
                self._frames.append(frame.copy())
            elapsed = time.monotonic() - t0
            sleep = interval - elapsed
            if sleep > 0:
                time.sleep(sleep)

    def stop(self, output_path: str) -> dict:
        if not self._thread:
            return {"error": "not recording"}

        self._stop.set()
        self._thread.join(timeout=5)
        try:
            self._cam.stop()
        except Exception:
            pass

        frames = self._frames
        if not frames:
            return {"error": "no frames captured"}

        duration_s = time.monotonic() - self._started_at
        h, w = frames[0].shape[:2]

        Path(output_path).parent.mkdir(parents=True, exist_ok=True)

        fourcc = _cv2.VideoWriter_fourcc(*"mp4v")
        writer = _cv2.VideoWriter(output_path, fourcc, self.fps, (w, h))
        for f in frames:
            writer.write(f)
        writer.release()

        size_mb = os.path.getsize(output_path) / (1024 * 1024)

        return {
            "output_path":  output_path,
            "frame_count":  len(frames),
            "fps":          self.fps,
            "duration_s":   round(duration_s, 1),
            "resolution":   f"{w}x{h}",
            "size_mb":      round(size_mb, 2),
        }


# Global recorder instance (one recording at a time)
_active: Optional[_Recorder] = None


def start_recording(fps: int = 5, region: Optional[tuple] = None) -> dict:
    global _active
    if _active is not None:
        return {"error": "already recording — call stop_recording() first"}
    _active = _Recorder(fps=fps, region=region)
    try:
        _active.start()
        return {"status": "recording", "fps": fps}
    except Exception as exc:
        _active = None
        return {"error": str(exc)}


def stop_recording(output_path: str) -> dict:
    global _active
    if _active is None:
        return {"error": "not recording"}
    result = _active.stop(output_path)
    _active = None
    return result
