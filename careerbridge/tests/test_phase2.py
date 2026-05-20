# test_phase2.py — Phase 2: Frame Capture Layer
# SCHEMA_VERSION: 1
#
# Unit tests: CaptureFrame validation, region resolution, backend selection,
#             window-not-found error path — all without touching real hardware.
# Integration tests (marked): latency benchmark, real DXcam grab.
#             Run with: pytest -m integration

from __future__ import annotations

import time
import unittest.mock as mock
from typing import Optional

import numpy as np
import pytest

from careerbridge.capture import (
    CaptureBackend,
    CaptureFrame,
    CaptureSession,
    _MSSBackend,
    _available_backend,
    _find_window,
    _resolve_region,
    _window_bbox,
    grab_once,
)
from careerbridge.errors import CaptureError, ErrorCode
from careerbridge.schema import BoundingBox


# ── Helpers ────────────────────────────────────────────────────────────────────

def _make_frame(
    w: int = 100,
    h: int = 80,
    frame_id: int = 0,
    backend: CaptureBackend = CaptureBackend.MSS,
    region: Optional[BoundingBox] = None,
) -> CaptureFrame:
    bbox = BoundingBox(x=0, y=0, w=w, h=h)
    return CaptureFrame(
        frame_id=frame_id,
        timestamp=time.monotonic(),
        data=np.zeros((h, w, 4), dtype=np.uint8),
        window_title="Test Window",
        window_bbox=bbox,
        region=region,
        backend=backend,
    )


def _make_bgra(w: int = 200, h: int = 150) -> np.ndarray:
    return np.zeros((h, w, 4), dtype=np.uint8)


# ── CaptureFrame validation ────────────────────────────────────────────────────

class TestCaptureFrameValidation:
    def test_valid_frame_constructs(self):
        f = _make_frame()
        assert f.frame_id == 0
        assert f.width == 100
        assert f.height == 80

    def test_negative_frame_id_rejected(self):
        with pytest.raises(ValueError, match="frame_id must be >= 0"):
            _make_frame(frame_id=-1)

    def test_zero_timestamp_rejected(self):
        bbox = BoundingBox(x=0, y=0, w=10, h=10)
        with pytest.raises(ValueError, match="timestamp must be > 0"):
            CaptureFrame(
                frame_id=0,
                timestamp=0.0,
                data=np.zeros((10, 10, 4), dtype=np.uint8),
                window_title="T",
                window_bbox=bbox,
                region=None,
                backend=CaptureBackend.MSS,
            )

    def test_negative_timestamp_rejected(self):
        bbox = BoundingBox(x=0, y=0, w=10, h=10)
        with pytest.raises(ValueError, match="timestamp must be > 0"):
            CaptureFrame(
                frame_id=0,
                timestamp=-1.0,
                data=np.zeros((10, 10, 4), dtype=np.uint8),
                window_title="T",
                window_bbox=bbox,
                region=None,
                backend=CaptureBackend.MSS,
            )

    def test_wrong_ndim_rejected(self):
        bbox = BoundingBox(x=0, y=0, w=10, h=10)
        with pytest.raises(ValueError, match="shape \\(h, w, 4\\)"):
            CaptureFrame(
                frame_id=0,
                timestamp=1.0,
                data=np.zeros((10, 10), dtype=np.uint8),  # 2-D, not 3-D
                window_title="T",
                window_bbox=bbox,
                region=None,
                backend=CaptureBackend.MSS,
            )

    def test_wrong_channel_count_rejected(self):
        bbox = BoundingBox(x=0, y=0, w=10, h=10)
        with pytest.raises(ValueError, match="shape \\(h, w, 4\\)"):
            CaptureFrame(
                frame_id=0,
                timestamp=1.0,
                data=np.zeros((10, 10, 3), dtype=np.uint8),  # BGR, not BGRA
                window_title="T",
                window_bbox=bbox,
                region=None,
                backend=CaptureBackend.MSS,
            )

    def test_wrong_dtype_rejected(self):
        bbox = BoundingBox(x=0, y=0, w=10, h=10)
        with pytest.raises(ValueError, match="uint8"):
            CaptureFrame(
                frame_id=0,
                timestamp=1.0,
                data=np.zeros((10, 10, 4), dtype=np.float32),
                window_title="T",
                window_bbox=bbox,
                region=None,
                backend=CaptureBackend.MSS,
            )

    def test_width_height_properties(self):
        f = _make_frame(w=320, h=240)
        assert f.width == 320
        assert f.height == 240

    def test_active_bbox_no_region(self):
        f = _make_frame(w=100, h=80, region=None)
        assert f.active_bbox == f.window_bbox

    def test_active_bbox_with_region(self):
        region = BoundingBox(x=10, y=10, w=50, h=40)
        f = _make_frame(w=100, h=80, region=region)
        assert f.active_bbox == region

    def test_backend_stored(self):
        f = _make_frame(backend=CaptureBackend.DXCAM)
        assert f.backend == CaptureBackend.DXCAM

    def test_frame_id_zero_valid(self):
        f = _make_frame(frame_id=0)
        assert f.frame_id == 0

    def test_large_frame_id_valid(self):
        f = _make_frame(frame_id=999999)
        assert f.frame_id == 999999


# ── Region resolution ─────────────────────────────────────────────────────────

class TestResolveRegion:
    def test_none_region_returns_window_bbox(self):
        win = BoundingBox(x=100, y=200, w=800, h=600)
        result = _resolve_region(win, None)
        assert result == win

    def test_region_inside_window_unchanged(self):
        win = BoundingBox(x=0, y=0, w=1000, h=800)
        reg = BoundingBox(x=100, y=100, w=200, h=200)
        result = _resolve_region(win, reg)
        assert result == reg

    def test_region_clamped_left(self):
        win = BoundingBox(x=100, y=0, w=800, h=600)
        # region starts before window left edge
        reg = BoundingBox(x=50, y=10, w=200, h=100)
        result = _resolve_region(win, reg)
        assert result.x == 100          # clamped to window.x
        assert result.w == 150          # 50+200=250, clamped to 100+200=300 → 300-100=200... wait
        # x1 = max(100, 50) = 100
        # x2 = min(100+800, 50+200) = min(900, 250) = 250
        # w = 250-100 = 150
        assert result.w == 150

    def test_region_clamped_right(self):
        win = BoundingBox(x=0, y=0, w=800, h=600)
        reg = BoundingBox(x=700, y=10, w=200, h=100)
        result = _resolve_region(win, reg)
        # x1=700, x2=min(800, 900)=800, w=100
        assert result.x == 700
        assert result.w == 100

    def test_region_clamped_top(self):
        win = BoundingBox(x=0, y=100, w=800, h=600)
        reg = BoundingBox(x=0, y=50, w=100, h=200)
        result = _resolve_region(win, reg)
        assert result.y == 100
        assert result.h == 150  # y1=100, y2=min(700,250)=250, h=150

    def test_region_clamped_bottom(self):
        win = BoundingBox(x=0, y=0, w=800, h=600)
        reg = BoundingBox(x=0, y=500, w=100, h=200)
        result = _resolve_region(win, reg)
        assert result.y == 500
        assert result.h == 100  # y2=min(600,700)=600, h=100

    def test_non_intersecting_region_raises(self):
        win = BoundingBox(x=0, y=0, w=800, h=600)
        reg = BoundingBox(x=900, y=700, w=100, h=100)
        with pytest.raises(CaptureError) as exc:
            _resolve_region(win, reg)
        assert exc.value.code == ErrorCode.CAPTURE_FRAME_TIMEOUT

    def test_touching_edge_non_intersecting_raises(self):
        win = BoundingBox(x=0, y=0, w=800, h=600)
        reg = BoundingBox(x=800, y=0, w=100, h=100)  # x starts exactly at right edge
        with pytest.raises(CaptureError):
            _resolve_region(win, reg)

    def test_exact_window_region_accepted(self):
        win = BoundingBox(x=10, y=20, w=300, h=200)
        result = _resolve_region(win, win)
        assert result == win

    def test_region_larger_than_window_clamped_to_window(self):
        win = BoundingBox(x=0, y=0, w=800, h=600)
        reg = BoundingBox(x=-100, y=-100, w=2000, h=2000)
        result = _resolve_region(win, reg)
        assert result == win


# ── Backend selection ─────────────────────────────────────────────────────────

class TestAvailableBackend:
    def test_dxcam_preferred_when_available(self):
        with mock.patch("careerbridge.capture._DXCAM_AVAILABLE", True):
            assert _available_backend() == CaptureBackend.DXCAM

    def test_mss_fallback_when_dxcam_unavailable(self):
        with mock.patch("careerbridge.capture._DXCAM_AVAILABLE", False), \
             mock.patch("careerbridge.capture._MSS_AVAILABLE", True):
            assert _available_backend() == CaptureBackend.MSS

    def test_raises_when_neither_available(self):
        with mock.patch("careerbridge.capture._DXCAM_AVAILABLE", False), \
             mock.patch("careerbridge.capture._MSS_AVAILABLE", False):
            with pytest.raises(CaptureError) as exc:
                _available_backend()
            assert exc.value.code == ErrorCode.CAPTURE_INIT_FAILED


# ── Window lookup ──────────────────────────────────────────────────────────────

class TestFindWindow:
    def _mock_win(self, title: str):
        w = mock.MagicMock()
        w.title = title
        w.left = 0
        w.top = 0
        w.width = 800
        w.height = 600
        return w

    def test_returns_first_match(self):
        wins = [self._mock_win("IXBrowser — Profile 1"), self._mock_win("Notepad")]
        with mock.patch("careerbridge.capture.gw.getAllWindows", return_value=wins):
            result = _find_window("ixbrowser")
        assert result.title == "IXBrowser — Profile 1"

    def test_case_insensitive_match(self):
        wins = [self._mock_win("IXBrowser")]
        with mock.patch("careerbridge.capture.gw.getAllWindows", return_value=wins):
            result = _find_window("IXBROWSER")
        assert result.title == "IXBrowser"

    def test_partial_title_match(self):
        wins = [self._mock_win("Google Chrome — Assessment")]
        with mock.patch("careerbridge.capture.gw.getAllWindows", return_value=wins):
            result = _find_window("Assessment")
        assert result is not None

    def test_not_found_raises_capture_error(self):
        with mock.patch("careerbridge.capture.gw.getAllWindows", return_value=[]):
            with pytest.raises(CaptureError) as exc:
                _find_window("NonExistent")
        assert exc.value.code == ErrorCode.CAPTURE_WINDOW_NOT_FOUND

    def test_error_includes_title_in_context(self):
        with mock.patch("careerbridge.capture.gw.getAllWindows", return_value=[]):
            with pytest.raises(CaptureError) as exc:
                _find_window("MyTitle")
        assert exc.value.context["title"] == "MyTitle"


# ── Window bbox ───────────────────────────────────────────────────────────────

class TestWindowBbox:
    def _mock_win(self, left, top, width, height):
        w = mock.MagicMock()
        w.left = left
        w.top = top
        w.width = width
        w.height = height
        return w

    def test_normal_window(self):
        win = self._mock_win(100, 200, 800, 600)
        bbox = _window_bbox(win)
        assert bbox.x == 100
        assert bbox.y == 200
        assert bbox.w == 800
        assert bbox.h == 600

    def test_zero_width_clamped_to_one(self):
        win = self._mock_win(0, 0, 0, 100)
        bbox = _window_bbox(win)
        assert bbox.w == 1

    def test_zero_height_clamped_to_one(self):
        win = self._mock_win(0, 0, 100, 0)
        bbox = _window_bbox(win)
        assert bbox.h == 1

    def test_negative_width_clamped_to_one(self):
        win = self._mock_win(0, 0, -50, 100)
        bbox = _window_bbox(win)
        assert bbox.w == 1


# ── MSS backend unit ─────────────────────────────────────────────────────────

def _make_mss_backend(sct_mock) -> _MSSBackend:
    """Construct _MSSBackend bypassing __init__ (avoids module-level _mss dependency)."""
    backend = _MSSBackend.__new__(_MSSBackend)
    backend._sct = sct_mock
    return backend


class TestMSSBackend:
    def test_grab_returns_bgra_array(self):
        fake_raw = np.zeros((100, 200, 4), dtype=np.uint8)
        mock_sct = mock.MagicMock()
        mock_sct.grab.return_value = fake_raw

        backend = _make_mss_backend(mock_sct)
        region = BoundingBox(x=0, y=0, w=200, h=100)
        result = backend.grab(region)

        assert result.shape == (100, 200, 4)
        assert result.dtype == np.uint8

    def test_grab_calls_with_correct_monitor(self):
        fake_raw = np.zeros((50, 80, 4), dtype=np.uint8)
        mock_sct = mock.MagicMock()
        mock_sct.grab.return_value = fake_raw

        backend = _make_mss_backend(mock_sct)
        region = BoundingBox(x=10, y=20, w=80, h=50)
        backend.grab(region)

        call_args = mock_sct.grab.call_args[0][0]
        assert call_args["left"] == 10
        assert call_args["top"] == 20
        assert call_args["width"] == 80
        assert call_args["height"] == 50

    def test_close_suppresses_exceptions(self):
        mock_sct = mock.MagicMock()
        mock_sct.close.side_effect = RuntimeError("forced error")

        backend = _make_mss_backend(mock_sct)
        backend.close()  # must not raise


# ── CaptureSession unit ───────────────────────────────────────────────────────

class TestCaptureSession:
    def _mock_grab_backend(self, shape=(600, 800, 4)):
        backend_mock = mock.MagicMock()
        backend_mock.grab.return_value = np.zeros(shape, dtype=np.uint8)
        return backend_mock

    def _mock_window(self, title="Test", left=0, top=0, width=800, height=600):
        w = mock.MagicMock()
        w.title = title
        w.left = left
        w.top = top
        w.width = width
        w.height = height
        return w

    def test_frame_counter_increments(self):
        session = CaptureSession.__new__(CaptureSession)
        session._frame_counter = 0
        session._closed = False
        session._backend = self._mock_grab_backend()
        session._backend_type = CaptureBackend.MSS

        win = self._mock_window()
        with mock.patch("careerbridge.capture.gw.getAllWindows", return_value=[win]):
            f0 = session.grab("Test")
            f1 = session.grab("Test")
            f2 = session.grab("Test")

        assert f0.frame_id == 0
        assert f1.frame_id == 1
        assert f2.frame_id == 2

    def test_grab_returns_capture_frame(self):
        session = CaptureSession.__new__(CaptureSession)
        session._frame_counter = 0
        session._closed = False
        session._backend = self._mock_grab_backend()
        session._backend_type = CaptureBackend.MSS

        win = self._mock_window()
        with mock.patch("careerbridge.capture.gw.getAllWindows", return_value=[win]):
            frame = session.grab("Test")

        assert isinstance(frame, CaptureFrame)
        assert frame.backend == CaptureBackend.MSS

    def test_grab_after_close_raises(self):
        session = CaptureSession.__new__(CaptureSession)
        session._frame_counter = 0
        session._closed = True
        session._backend = self._mock_grab_backend()
        session._backend_type = CaptureBackend.MSS

        with pytest.raises(CaptureError) as exc:
            session.grab("Test")
        assert exc.value.code == ErrorCode.CAPTURE_INIT_FAILED

    def test_context_manager_closes_on_exit(self):
        backend_mock = self._mock_grab_backend()

        with mock.patch("careerbridge.capture._MSSBackend", return_value=backend_mock):
            session = CaptureSession(backend=CaptureBackend.MSS)

        session.close()
        assert session._closed is True

    def test_double_close_safe(self):
        backend_mock = self._mock_grab_backend()

        with mock.patch("careerbridge.capture._MSSBackend", return_value=backend_mock):
            session = CaptureSession(backend=CaptureBackend.MSS)

        session.close()
        session.close()  # second close must not raise or double-release

    def test_grab_with_region(self):
        session = CaptureSession.__new__(CaptureSession)
        session._frame_counter = 0
        session._closed = False
        session._backend = self._mock_grab_backend(shape=(100, 200, 4))
        session._backend_type = CaptureBackend.MSS

        win = self._mock_window(width=800, height=600)
        region = BoundingBox(x=100, y=100, w=200, h=100)
        with mock.patch("careerbridge.capture.gw.getAllWindows", return_value=[win]):
            frame = session.grab("Test", region=region)

        assert frame.region == region

    def test_window_title_stored_in_frame(self):
        session = CaptureSession.__new__(CaptureSession)
        session._frame_counter = 0
        session._closed = False
        session._backend = self._mock_grab_backend()
        session._backend_type = CaptureBackend.MSS

        win = self._mock_window(title="IXBrowser — Profile 5")
        with mock.patch("careerbridge.capture.gw.getAllWindows", return_value=[win]):
            frame = session.grab("IXBrowser")

        assert frame.window_title == "IXBrowser — Profile 5"

    def test_window_not_found_propagates(self):
        session = CaptureSession.__new__(CaptureSession)
        session._frame_counter = 0
        session._closed = False
        session._backend = self._mock_grab_backend()
        session._backend_type = CaptureBackend.MSS

        with mock.patch("careerbridge.capture.gw.getAllWindows", return_value=[]):
            with pytest.raises(CaptureError) as exc:
                session.grab("NoSuchWindow")
        assert exc.value.code == ErrorCode.CAPTURE_WINDOW_NOT_FOUND


# ── grab_once convenience ─────────────────────────────────────────────────────

class TestGrabOnce:
    def _make_win(self, title="TestWin", left=0, top=0, width=800, height=600):
        win = mock.MagicMock()
        win.title = title
        win.left = left
        win.top = top
        win.width = width
        win.height = height
        return win

    def test_grab_once_returns_frame(self):
        fake_data = np.zeros((600, 800, 4), dtype=np.uint8)
        mock_backend_inst = mock.MagicMock()
        mock_backend_inst.grab.return_value = fake_data

        win = self._make_win()
        with mock.patch("careerbridge.capture.gw.getAllWindows", return_value=[win]), \
             mock.patch("careerbridge.capture._MSSBackend", return_value=mock_backend_inst):
            frame = grab_once("TestWin", backend=CaptureBackend.MSS)

        assert isinstance(frame, CaptureFrame)
        assert frame.frame_id == 0

    def test_grab_once_closes_session(self):
        """grab_once must not leave the backend open."""
        fake_data = np.zeros((600, 800, 4), dtype=np.uint8)
        mock_backend_inst = mock.MagicMock()
        mock_backend_inst.grab.return_value = fake_data

        win = self._make_win()
        with mock.patch("careerbridge.capture.gw.getAllWindows", return_value=[win]), \
             mock.patch("careerbridge.capture._MSSBackend", return_value=mock_backend_inst):
            grab_once("TestWin", backend=CaptureBackend.MSS)

        mock_backend_inst.close.assert_called_once()


# ── Integration: real DXcam grab ─────────────────────────────────────────────

@pytest.mark.integration
class TestIntegrationDXcam:
    def test_grab_returns_bgra_array(self):
        """Requires DXcam installed and a visible desktop window."""
        import careerbridge.capture as cap
        if not cap._DXCAM_AVAILABLE:
            pytest.skip("DXcam not available")

        wins = [w for w in __import__("pygetwindow").getAllWindows() if w.title.strip()]
        if not wins:
            pytest.skip("No visible windows to capture")

        title_substr = wins[0].title[:10]
        with CaptureSession(backend=CaptureBackend.DXCAM) as session:
            frame = session.grab(title_substr)

        assert frame.data.ndim == 3
        assert frame.data.shape[2] == 4
        assert frame.data.dtype == np.uint8
        assert frame.width > 0
        assert frame.height > 0

    def test_latency_under_100ms(self):
        """Single grab round-trip must be <100ms on DXcam."""
        import careerbridge.capture as cap
        if not cap._DXCAM_AVAILABLE:
            pytest.skip("DXcam not available")

        wins = [w for w in __import__("pygetwindow").getAllWindows() if w.title.strip()]
        if not wins:
            pytest.skip("No visible windows")

        title_substr = wins[0].title[:10]
        with CaptureSession(backend=CaptureBackend.DXCAM) as session:
            t0 = time.perf_counter()
            session.grab(title_substr)
            elapsed_ms = (time.perf_counter() - t0) * 1000

        assert elapsed_ms < 100, f"Grab took {elapsed_ms:.1f}ms (limit 100ms)"

    def test_30_consecutive_grabs_no_loss(self):
        """30 consecutive grabs must all return valid frames (zero frame loss)."""
        import careerbridge.capture as cap
        if not cap._DXCAM_AVAILABLE:
            pytest.skip("DXcam not available")

        wins = [w for w in __import__("pygetwindow").getAllWindows() if w.title.strip()]
        if not wins:
            pytest.skip("No visible windows")

        title_substr = wins[0].title[:10]
        frames = []
        with CaptureSession(backend=CaptureBackend.DXCAM) as session:
            for _ in range(30):
                frames.append(session.grab(title_substr))

        assert len(frames) == 30
        for i, f in enumerate(frames):
            assert f.frame_id == i
            assert f.data is not None
            assert f.data.shape[2] == 4
