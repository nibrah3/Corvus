# test_phase4_5.py — Phase 4–5: UIA + OCR + Identity
# SCHEMA_VERSION: 1
#
# All tests are unit (mocked hardware/libraries).
# UIA: mocked pywinauto; OCR: mocked PaddleOCR; Identity: real imagehash.
# Integration tests marked @pytest.mark.integration require a live desktop.

from __future__ import annotations

import time
import unittest.mock as mock

import numpy as np
import pytest

from careerbridge.capture import CaptureFrame
from careerbridge.errors import ErrorCode, PerceptionError
from careerbridge.perception.identity import (
    compute_element_phash,
    elements_visually_match,
    phash_distance,
)
from careerbridge.perception.ocr import (
    _bgra_to_bgr,
    _parse_paddle_result,
    extract_ocr_elements,
)
from careerbridge.perception.uia import (
    _bbox_in_region,
    _map_control_type,
    _rect_to_bbox,
    extract_uia_elements,
)
from careerbridge.schema import BoundingBox, UIElement
from careerbridge.types import ElementType, PerceptionSource


# ── Test helpers ──────────────────────────────────────────────────────────────

def _bgra_frame(h: int = 100, w: int = 100, fill: int = 128, frame_id: int = 0) -> CaptureFrame:
    from careerbridge.capture import CaptureBackend
    data = np.full((h, w, 4), fill, dtype=np.uint8)
    bbox = BoundingBox(x=0, y=0, w=w, h=h)
    return CaptureFrame(
        frame_id=frame_id,
        timestamp=time.monotonic(),
        data=data,
        window_title="Test",
        window_bbox=bbox,
        region=None,
        backend=CaptureBackend.MSS,
    )


def _ui_element(text="OK", x=10, y=10, w=50, h=20, etype=ElementType.BUTTON) -> UIElement:
    return UIElement(
        element_type=etype,
        text=text,
        bbox=BoundingBox(x=x, y=y, w=w, h=h),
        confidence=0.9,
        source=PerceptionSource.UIA,
        frame_id=0,
    )


# ══════════════════════════════════════════════════════════════════════════════
# UIA helpers
# ══════════════════════════════════════════════════════════════════════════════

class TestMapControlType:
    def test_button_maps_to_button(self):
        assert _map_control_type("button") == ElementType.BUTTON

    def test_case_insensitive(self):
        assert _map_control_type("Button") == ElementType.BUTTON
        assert _map_control_type("BUTTON") == ElementType.BUTTON

    def test_radiobutton_maps_to_radio(self):
        assert _map_control_type("radiobutton") == ElementType.RADIO

    def test_checkbox_maps_to_checkbox(self):
        assert _map_control_type("checkbox") == ElementType.CHECKBOX

    def test_edit_maps_to_input(self):
        assert _map_control_type("edit") == ElementType.INPUT

    def test_document_maps_to_input(self):
        assert _map_control_type("document") == ElementType.INPUT

    def test_text_maps_to_text(self):
        assert _map_control_type("text") == ElementType.TEXT

    def test_static_maps_to_text(self):
        assert _map_control_type("static") == ElementType.TEXT

    def test_combobox_maps_to_dropdown(self):
        assert _map_control_type("combobox") == ElementType.DROPDOWN

    def test_unknown_type_maps_to_unknown(self):
        assert _map_control_type("weirdcontrol") == ElementType.UNKNOWN

    def test_titlebar_returns_none(self):
        assert _map_control_type("titlebar") is None

    def test_scrollbar_returns_none(self):
        assert _map_control_type("scrollbar") is None

    def test_window_returns_none(self):
        assert _map_control_type("window") is None

    def test_pane_returns_none(self):
        assert _map_control_type("pane") is None

    def test_empty_string_returns_unknown(self):
        assert _map_control_type("") == ElementType.UNKNOWN


class TestRectToBbox:
    def _rect(self, left, top, right, bottom):
        r = mock.MagicMock()
        r.left = left
        r.top = top
        r.right = right
        r.bottom = bottom
        return r

    def test_normal_rect(self):
        bbox = _rect_to_bbox(self._rect(10, 20, 110, 70))
        assert bbox == BoundingBox(x=10, y=20, w=100, h=50)

    def test_zero_width_returns_none(self):
        assert _rect_to_bbox(self._rect(0, 0, 0, 50)) is None

    def test_zero_height_returns_none(self):
        assert _rect_to_bbox(self._rect(0, 0, 50, 0)) is None

    def test_negative_width_returns_none(self):
        assert _rect_to_bbox(self._rect(50, 0, 10, 100)) is None

    def test_exception_returns_none(self):
        bad = mock.MagicMock()
        bad.right = mock.PropertyMock(side_effect=RuntimeError)
        assert _rect_to_bbox(bad) is None


class TestBboxInRegion:
    def test_none_region_always_true(self):
        bbox = BoundingBox(x=100, y=100, w=50, h=50)
        assert _bbox_in_region(bbox, None) is True

    def test_fully_inside_region(self):
        region = BoundingBox(x=0, y=0, w=500, h=500)
        bbox = BoundingBox(x=100, y=100, w=50, h=50)
        assert _bbox_in_region(bbox, region) is True

    def test_fully_outside_region(self):
        region = BoundingBox(x=0, y=0, w=100, h=100)
        bbox = BoundingBox(x=200, y=200, w=50, h=50)
        assert _bbox_in_region(bbox, region) is False

    def test_partially_overlapping(self):
        region = BoundingBox(x=0, y=0, w=100, h=100)
        bbox = BoundingBox(x=80, y=80, w=50, h=50)
        assert _bbox_in_region(bbox, region) is True

    def test_touching_right_edge_excluded(self):
        region = BoundingBox(x=0, y=0, w=100, h=100)
        bbox = BoundingBox(x=100, y=0, w=50, h=50)
        assert _bbox_in_region(bbox, region) is False

    def test_touching_bottom_edge_excluded(self):
        region = BoundingBox(x=0, y=0, w=100, h=100)
        bbox = BoundingBox(x=0, y=100, w=50, h=50)
        assert _bbox_in_region(bbox, region) is False


class TestExtractUiaElements:
    def _mock_ctrl(self, ctrl_type="button", name="OK", left=0, top=0, right=80, bottom=30):
        rect = mock.MagicMock()
        rect.left = left
        rect.top = top
        rect.right = right
        rect.bottom = bottom

        info = mock.MagicMock()
        info.control_type = ctrl_type
        info.name = name
        info.rectangle = rect

        ctrl = mock.MagicMock()
        ctrl.element_info = info
        return ctrl

    def _mock_app(self, controls):
        win = mock.MagicMock()
        win.descendants.return_value = controls
        app = mock.MagicMock()
        app.top_window.return_value = win
        return app

    def test_extracts_button_element(self):
        ctrl = self._mock_ctrl("button", "Submit", 10, 20, 110, 50)
        app = self._mock_app([ctrl])

        with mock.patch("careerbridge.perception.uia._PWA_AVAILABLE", True), \
             mock.patch("careerbridge.perception.uia._pwa") as mock_pwa:
            mock_pwa.Application.return_value.connect.return_value = app
            results = extract_uia_elements("TestWin", frame_id=5)

        assert len(results) == 1
        assert results[0].element_type == ElementType.BUTTON
        assert results[0].text == "Submit"
        assert results[0].frame_id == 5
        assert results[0].source == PerceptionSource.UIA

    def test_skips_titlebar(self):
        ctrl = self._mock_ctrl("titlebar", "Window Title")
        app = self._mock_app([ctrl])

        with mock.patch("careerbridge.perception.uia._PWA_AVAILABLE", True), \
             mock.patch("careerbridge.perception.uia._pwa") as mock_pwa:
            mock_pwa.Application.return_value.connect.return_value = app
            results = extract_uia_elements("TestWin", frame_id=0)

        assert len(results) == 0

    def test_skips_degenerate_rect(self):
        ctrl = self._mock_ctrl("button", "Bad", 0, 0, 0, 0)  # zero-size
        app = self._mock_app([ctrl])

        with mock.patch("careerbridge.perception.uia._PWA_AVAILABLE", True), \
             mock.patch("careerbridge.perception.uia._pwa") as mock_pwa:
            mock_pwa.Application.return_value.connect.return_value = app
            results = extract_uia_elements("TestWin", frame_id=0)

        assert len(results) == 0

    def test_region_filter_excludes_outside(self):
        ctrl = self._mock_ctrl("button", "Far Away", 500, 500, 600, 530)
        app = self._mock_app([ctrl])
        region = BoundingBox(x=0, y=0, w=200, h=200)

        with mock.patch("careerbridge.perception.uia._PWA_AVAILABLE", True), \
             mock.patch("careerbridge.perception.uia._pwa") as mock_pwa:
            mock_pwa.Application.return_value.connect.return_value = app
            results = extract_uia_elements("TestWin", frame_id=0, region=region)

        assert len(results) == 0

    def test_region_filter_includes_intersecting(self):
        ctrl = self._mock_ctrl("button", "Visible", 50, 50, 150, 80)
        app = self._mock_app([ctrl])
        region = BoundingBox(x=0, y=0, w=200, h=200)

        with mock.patch("careerbridge.perception.uia._PWA_AVAILABLE", True), \
             mock.patch("careerbridge.perception.uia._pwa") as mock_pwa:
            mock_pwa.Application.return_value.connect.return_value = app
            results = extract_uia_elements("TestWin", frame_id=0, region=region)

        assert len(results) == 1

    def test_raises_when_pwa_unavailable(self):
        with mock.patch("careerbridge.perception.uia._PWA_AVAILABLE", False):
            with pytest.raises(PerceptionError) as exc:
                extract_uia_elements("TestWin", frame_id=0)
        assert exc.value.code == ErrorCode.PERCEPTION_UIA_UNAVAILABLE

    def test_raises_when_window_not_found(self):
        with mock.patch("careerbridge.perception.uia._PWA_AVAILABLE", True), \
             mock.patch("careerbridge.perception.uia._pwa") as mock_pwa:
            mock_pwa.Application.return_value.connect.side_effect = RuntimeError("not found")
            with pytest.raises(PerceptionError) as exc:
                extract_uia_elements("NoSuchWindow", frame_id=0)
        assert exc.value.code == ErrorCode.PERCEPTION_TIMEOUT

    def test_bad_control_skipped_not_raised(self):
        good = self._mock_ctrl("button", "Good", 0, 0, 100, 30)
        bad = mock.MagicMock()
        bad.element_info = mock.PropertyMock(side_effect=RuntimeError("explode"))
        app = self._mock_app([bad, good])

        with mock.patch("careerbridge.perception.uia._PWA_AVAILABLE", True), \
             mock.patch("careerbridge.perception.uia._pwa") as mock_pwa:
            mock_pwa.Application.return_value.connect.return_value = app
            results = extract_uia_elements("TestWin", frame_id=0)

        # bad control skipped, good one returned
        assert len(results) == 1
        assert results[0].text == "Good"

    def test_multiple_control_types(self):
        controls = [
            self._mock_ctrl("button",      "Submit",   0, 0, 80, 30),
            self._mock_ctrl("checkbox",    "Agree",    0, 40, 150, 65),
            self._mock_ctrl("radiobutton", "Option A", 0, 70, 150, 95),
            self._mock_ctrl("edit",        "",         0, 100, 200, 130),
        ]
        app = self._mock_app(controls)

        with mock.patch("careerbridge.perception.uia._PWA_AVAILABLE", True), \
             mock.patch("careerbridge.perception.uia._pwa") as mock_pwa:
            mock_pwa.Application.return_value.connect.return_value = app
            results = extract_uia_elements("TestWin", frame_id=0)

        types = [r.element_type for r in results]
        assert ElementType.BUTTON in types
        assert ElementType.CHECKBOX in types
        assert ElementType.RADIO in types
        assert ElementType.INPUT in types

    def test_confidence_is_0_9(self):
        ctrl = self._mock_ctrl("button", "OK", 0, 0, 80, 30)
        app = self._mock_app([ctrl])

        with mock.patch("careerbridge.perception.uia._PWA_AVAILABLE", True), \
             mock.patch("careerbridge.perception.uia._pwa") as mock_pwa:
            mock_pwa.Application.return_value.connect.return_value = app
            results = extract_uia_elements("TestWin", frame_id=0)

        assert results[0].confidence == 0.9

    def test_empty_descendants_returns_empty(self):
        app = self._mock_app([])

        with mock.patch("careerbridge.perception.uia._PWA_AVAILABLE", True), \
             mock.patch("careerbridge.perception.uia._pwa") as mock_pwa:
            mock_pwa.Application.return_value.connect.return_value = app
            results = extract_uia_elements("TestWin", frame_id=0)

        assert results == []


# ══════════════════════════════════════════════════════════════════════════════
# OCR helpers
# ══════════════════════════════════════════════════════════════════════════════

class TestBgraToBGR:
    def test_drops_alpha_channel(self):
        bgra = np.zeros((10, 10, 4), dtype=np.uint8)
        bgr = _bgra_to_bgr(bgra)
        assert bgr.shape == (10, 10, 3)

    def test_preserves_bgr_values(self):
        bgra = np.full((4, 4, 4), 200, dtype=np.uint8)
        bgr = _bgra_to_bgr(bgra)
        assert (bgr == 200).all()

    def test_non_square_input(self):
        bgra = np.zeros((30, 80, 4), dtype=np.uint8)
        bgr = _bgra_to_bgr(bgra)
        assert bgr.shape == (30, 80, 3)


class TestParsePaddleResult:
    def _quad(self, x1, y1, x2, y2):
        return [[x1, y1], [x2, y1], [x2, y2], [x1, y2]]

    def test_parses_single_line(self):
        result = [[
            [self._quad(0, 0, 100, 20), ("Hello world", 0.95)]
        ]]
        elements = _parse_paddle_result(result, 10, 20, frame_id=3, min_confidence=0.7)
        assert len(elements) == 1
        e = elements[0]
        assert e.text == "Hello world"
        assert abs(e.confidence - 0.95) < 0.001
        assert e.bbox.x == 10   # 0 + offset 10
        assert e.bbox.y == 20   # 0 + offset 20
        assert e.source == PerceptionSource.OCR
        assert e.frame_id == 3

    def test_offset_applied_to_bbox(self):
        result = [[
            [self._quad(5, 10, 55, 30), ("Text", 0.9)]
        ]]
        elements = _parse_paddle_result(result, 100, 200, frame_id=0, min_confidence=0.5)
        assert elements[0].bbox.x == 105   # 5 + 100
        assert elements[0].bbox.y == 210   # 10 + 200

    def test_low_confidence_filtered(self):
        result = [[
            [self._quad(0, 0, 50, 20), ("Low conf", 0.4)]
        ]]
        elements = _parse_paddle_result(result, 0, 0, frame_id=0, min_confidence=0.7)
        assert elements == []

    def test_empty_text_skipped(self):
        result = [[
            [self._quad(0, 0, 50, 20), ("   ", 0.95)]
        ]]
        elements = _parse_paddle_result(result, 0, 0, frame_id=0, min_confidence=0.5)
        assert elements == []

    def test_none_result_returns_empty(self):
        assert _parse_paddle_result(None, 0, 0, 0, 0.5) == []
        assert _parse_paddle_result([None], 0, 0, 0, 0.5) == []

    def test_multiple_lines(self):
        result = [[
            [self._quad(0, 0, 100, 20), ("Line one", 0.9)],
            [self._quad(0, 25, 100, 45), ("Line two", 0.85)],
        ]]
        elements = _parse_paddle_result(result, 0, 0, frame_id=0, min_confidence=0.5)
        assert len(elements) == 2
        assert {e.text for e in elements} == {"Line one", "Line two"}

    def test_element_type_is_text(self):
        result = [[
            [self._quad(0, 0, 80, 20), ("Word", 0.95)]
        ]]
        elements = _parse_paddle_result(result, 0, 0, frame_id=0, min_confidence=0.5)
        assert elements[0].element_type == ElementType.TEXT

    def test_bbox_width_at_least_one(self):
        # Degenerate quad where x1==x2
        result = [[
            [[[5, 0], [5, 0], [5, 20], [5, 20]], ("X", 0.9)]
        ]]
        elements = _parse_paddle_result(result, 0, 0, frame_id=0, min_confidence=0.5)
        assert elements[0].bbox.w >= 1
        assert elements[0].bbox.h >= 1


class TestExtractOcrElements:
    def _make_ocr_result(self, texts):
        """Build a fake PaddleOCR result list from (text, confidence, x, y, w, h) tuples."""
        lines = []
        for text, conf, x, y, w, h in texts:
            quad = [[x, y], [x+w, y], [x+w, y+h], [x, y+h]]
            lines.append([quad, (text, conf)])
        return [lines]

    def test_empty_regions_returns_empty(self):
        frame = _bgra_frame()
        result = extract_ocr_elements(frame, regions=())
        assert result == []

    def test_out_of_bounds_region_skipped(self):
        frame = _bgra_frame(h=100, w=100)
        oob_region = (BoundingBox(x=200, y=200, w=50, h=50),)
        # Should not raise — just skip the region
        with mock.patch("careerbridge.perception.ocr._PADDLEOCR_AVAILABLE", True), \
             mock.patch("careerbridge.perception.ocr._ocr_instance") as mock_ocr:
            result = extract_ocr_elements(frame, regions=oob_region)
        assert result == []

    def test_raises_when_paddleocr_unavailable(self):
        frame = _bgra_frame()
        region = (BoundingBox(x=0, y=0, w=50, h=50),)
        with mock.patch("careerbridge.perception.ocr._PADDLEOCR_AVAILABLE", False), \
             mock.patch("careerbridge.perception.ocr._ocr_instance", None):
            with pytest.raises(PerceptionError) as exc:
                extract_ocr_elements(frame, regions=region)
        assert exc.value.code == ErrorCode.PERCEPTION_UIA_UNAVAILABLE

    def test_ocr_result_parsed_and_returned(self):
        frame = _bgra_frame(h=200, w=300)
        region = BoundingBox(x=0, y=0, w=300, h=100)
        fake_result = self._make_ocr_result([("Question text", 0.92, 10, 5, 150, 20)])

        mock_ocr_inst = mock.MagicMock()
        mock_ocr_inst.ocr.return_value = fake_result

        with mock.patch("careerbridge.perception.ocr._PADDLEOCR_AVAILABLE", True), \
             mock.patch("careerbridge.perception.ocr._ocr_instance", mock_ocr_inst):
            results = extract_ocr_elements(frame, regions=(region,))

        assert len(results) == 1
        assert results[0].text == "Question text"
        assert results[0].source == PerceptionSource.OCR

    def test_multiple_regions_all_scanned(self):
        frame = _bgra_frame(h=400, w=400)
        regions = (
            BoundingBox(x=0, y=0, w=200, h=100),
            BoundingBox(x=0, y=200, w=200, h=100),
        )
        fake_result_1 = self._make_ocr_result([("Top text", 0.9, 0, 0, 100, 20)])
        fake_result_2 = self._make_ocr_result([("Bottom text", 0.88, 0, 0, 100, 20)])

        mock_ocr_inst = mock.MagicMock()
        mock_ocr_inst.ocr.side_effect = [fake_result_1, fake_result_2]

        with mock.patch("careerbridge.perception.ocr._PADDLEOCR_AVAILABLE", True), \
             mock.patch("careerbridge.perception.ocr._ocr_instance", mock_ocr_inst):
            results = extract_ocr_elements(frame, regions=regions)

        assert len(results) == 2
        texts = {r.text for r in results}
        assert "Top text" in texts
        assert "Bottom text" in texts

    def test_confidence_threshold_filters_results(self):
        frame = _bgra_frame(h=200, w=200)
        region = BoundingBox(x=0, y=0, w=200, h=100)
        fake_result = self._make_ocr_result([
            ("High conf", 0.95, 0, 0, 100, 20),
            ("Low conf",  0.50, 0, 30, 100, 20),
        ])

        mock_ocr_inst = mock.MagicMock()
        mock_ocr_inst.ocr.return_value = fake_result

        with mock.patch("careerbridge.perception.ocr._PADDLEOCR_AVAILABLE", True), \
             mock.patch("careerbridge.perception.ocr._ocr_instance", mock_ocr_inst):
            results = extract_ocr_elements(frame, regions=(region,), min_confidence=0.7)

        assert len(results) == 1
        assert results[0].text == "High conf"

    def test_ocr_failure_raises_perception_error(self):
        frame = _bgra_frame(h=100, w=100)
        region = BoundingBox(x=0, y=0, w=100, h=100)

        mock_ocr_inst = mock.MagicMock()
        mock_ocr_inst.ocr.side_effect = RuntimeError("GPU OOM")

        with mock.patch("careerbridge.perception.ocr._PADDLEOCR_AVAILABLE", True), \
             mock.patch("careerbridge.perception.ocr._ocr_instance", mock_ocr_inst):
            with pytest.raises(PerceptionError) as exc:
                extract_ocr_elements(frame, regions=(region,))
        assert exc.value.code == ErrorCode.PERCEPTION_TIMEOUT

    def test_frame_id_stamped_on_elements(self):
        frame = _bgra_frame(frame_id=42)
        region = BoundingBox(x=0, y=0, w=100, h=100)
        fake_result = self._make_ocr_result([("Text", 0.9, 0, 0, 50, 15)])

        mock_ocr_inst = mock.MagicMock()
        mock_ocr_inst.ocr.return_value = fake_result

        with mock.patch("careerbridge.perception.ocr._PADDLEOCR_AVAILABLE", True), \
             mock.patch("careerbridge.perception.ocr._ocr_instance", mock_ocr_inst):
            results = extract_ocr_elements(frame, regions=(region,))

        assert results[0].frame_id == 42


# ══════════════════════════════════════════════════════════════════════════════
# Identity / phash
# ══════════════════════════════════════════════════════════════════════════════

class TestComputeElementPhash:
    def test_returns_nonempty_string(self):
        frame = _bgra_frame(h=100, w=100, fill=128)
        elem = _ui_element(x=10, y=10, w=50, h=30)
        h = compute_element_phash(frame, elem)
        assert isinstance(h, str)
        assert len(h) > 0

    def test_same_region_same_hash(self):
        frame = _bgra_frame(h=100, w=100, fill=200)
        elem = _ui_element(x=0, y=0, w=100, h=100)
        h1 = compute_element_phash(frame, elem)
        h2 = compute_element_phash(frame, elem)
        assert h1 == h2

    def test_different_regions_different_hash(self):
        frame = _bgra_frame(h=100, w=100, fill=0)
        # Patch one region with different pixel values
        frame.data[0:40, 0:40] = 255

        elem_bright = _ui_element(x=0, y=0, w=40, h=40)
        elem_dark = _ui_element(x=60, y=60, w=40, h=40)

        h_bright = compute_element_phash(frame, elem_bright)
        h_dark = compute_element_phash(frame, elem_dark)
        assert h_bright != h_dark

    def test_out_of_bounds_element_returns_empty(self):
        frame = _bgra_frame(h=50, w=50)
        elem = _ui_element(x=200, y=200, w=50, h=50)
        h = compute_element_phash(frame, elem)
        assert h == ""

    def test_imagehash_unavailable_returns_empty(self):
        frame = _bgra_frame()
        elem = _ui_element()
        with mock.patch("careerbridge.perception.identity._IMAGEHASH_AVAILABLE", False):
            h = compute_element_phash(frame, elem)
        assert h == ""


class TestPhashDistance:
    def test_same_hash_distance_zero(self):
        frame = _bgra_frame(h=100, w=100, fill=128)
        elem = _ui_element(x=0, y=0, w=100, h=100)
        h = compute_element_phash(frame, elem)
        assert phash_distance(h, h) == 0

    def test_empty_hash_returns_max_distance(self):
        assert phash_distance("", "abc") == 64
        assert phash_distance("abc", "") == 64
        assert phash_distance("", "") == 64

    def test_distance_symmetric(self):
        frame = _bgra_frame(h=100, w=100, fill=0)
        frame.data[0:50, :] = 200
        e1 = _ui_element(x=0, y=0, w=100, h=50)
        e2 = _ui_element(x=0, y=50, w=100, h=50)
        h1 = compute_element_phash(frame, e1)
        h2 = compute_element_phash(frame, e2)
        assert phash_distance(h1, h2) == phash_distance(h2, h1)

    def test_distance_nonnegative(self):
        frame = _bgra_frame()
        e1 = _ui_element(x=0, y=0, w=50, h=50)
        e2 = _ui_element(x=50, y=50, w=50, h=50)
        h1 = compute_element_phash(frame, e1)
        h2 = compute_element_phash(frame, e2)
        assert phash_distance(h1, h2) >= 0


class TestElementsVisuallyMatch:
    def test_identical_hashes_match(self):
        frame = _bgra_frame(fill=150)
        elem = _ui_element(x=0, y=0, w=100, h=100)
        h = compute_element_phash(frame, elem)
        assert elements_visually_match(h, h)

    def test_empty_hashes_do_not_match(self):
        assert elements_visually_match("", "") is False

    def test_threshold_respected(self):
        frame = _bgra_frame(h=100, w=100, fill=0)
        frame.data[0:50, :] = 255

        e_top = _ui_element(x=0, y=0, w=100, h=50)
        e_bot = _ui_element(x=0, y=50, w=100, h=50)

        h_top = compute_element_phash(frame, e_top)
        h_bot = compute_element_phash(frame, e_bot)

        dist = phash_distance(h_top, h_bot)
        # With strict threshold (0), they should not match
        assert elements_visually_match(h_top, h_bot, threshold=0) is False
        # With max threshold, everything matches
        assert elements_visually_match(h_top, h_bot, threshold=64) is True


# ══════════════════════════════════════════════════════════════════════════════
# Integration
# ══════════════════════════════════════════════════════════════════════════════

@pytest.mark.integration
class TestIntegrationUIA:
    def test_extract_from_real_window(self):
        """Requires any visible window with native controls."""
        import pygetwindow as gw
        wins = [w for w in gw.getAllWindows() if w.title.strip()]
        if not wins:
            pytest.skip("No visible windows")
        title = wins[0].title
        try:
            results = extract_uia_elements(title, frame_id=0)
        except PerceptionError as e:
            if e.code == ErrorCode.PERCEPTION_TIMEOUT:
                pytest.skip(f"Could not connect to window: {e}")
            raise
        assert isinstance(results, list)
