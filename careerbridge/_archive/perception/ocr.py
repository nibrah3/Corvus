# ocr.py — Phase 5: RapidOCR text extractor
# SCHEMA_VERSION: 2
#
# Single responsibility: extract text regions from CaptureFrame dirty areas
# using rapidocr-onnxruntime. Region-based only — never processes the full frame.
#
# MUST NOT: interpret meaning, make decisions, read pixels outside the
# dirty regions supplied by frame_diff.compute_diff().

from __future__ import annotations

from typing import Optional

import numpy as np

from ..capture import CaptureFrame
from ..errors import ErrorCode, PerceptionError
from ..schema import BoundingBox, UIElement
from ..types import ElementType, PerceptionSource

# ── Backend detection ─────────────────────────────────────────────────────────

try:
    from rapidocr_onnxruntime import RapidOCR as _RapidOCR
    _RAPIDOCR_AVAILABLE = True
except Exception:
    _RAPIDOCR_AVAILABLE = False

# Lazy singleton — initialised on first use, not at import time.
_ocr_instance: Optional[object] = None

def _get_ocr():
    global _ocr_instance
    if _ocr_instance is None:
        if not _RAPIDOCR_AVAILABLE:
            raise PerceptionError(
                ErrorCode.PERCEPTION_UIA_UNAVAILABLE,
                "rapidocr_onnxruntime is not installed. Run: pip install rapidocr-onnxruntime",
            )
        _ocr_instance = _RapidOCR()
    return _ocr_instance


# ── BGRA → BGR conversion ─────────────────────────────────────────────────────

def _bgra_to_bgr(data: np.ndarray) -> np.ndarray:
    """Drop alpha channel. Returns (h, w, 3) uint8."""
    return data[:, :, :3]


# ── OCR result parsing ────────────────────────────────────────────────────────

def _parse_rapid_result(
    result,
    region_offset_x: int,
    region_offset_y: int,
    frame_id: int,
    min_confidence: float,
) -> list[UIElement]:
    """
    Convert one RapidOCR result to UIElement list.

    RapidOCR returns:
        result: [[box, text, confidence], ...] or None
        box:    [[x1,y1],[x2,y1],[x2,y2],[x1,y2]]  (4-point quad)

    Coordinates are relative to the cropped region; we add the region offset
    to convert back to absolute screen pixels.
    """
    elements: list[UIElement] = []
    if not result:
        return elements

    for item in result:
        try:
            box, text, confidence = item
            confidence = float(confidence)
            if confidence < min_confidence:
                continue
            text = text.strip()
            if not text:
                continue

            xs = [int(p[0]) for p in box]
            ys = [int(p[1]) for p in box]
            x1, x2 = min(xs), max(xs)
            y1, y2 = min(ys), max(ys)
            w = max(1, x2 - x1)
            h = max(1, y2 - y1)

            bbox = BoundingBox(
                x=region_offset_x + x1,
                y=region_offset_y + y1,
                w=w,
                h=h,
            )
            elements.append(UIElement(
                element_type=ElementType.TEXT,
                text=text,
                bbox=bbox,
                confidence=float(confidence),
                source=PerceptionSource.OCR,
                frame_id=frame_id,
            ))
        except Exception:
            continue

    return elements


# ── Public API ────────────────────────────────────────────────────────────────

def extract_ocr_elements(
    frame: CaptureFrame,
    regions: tuple,  # tuple[BoundingBox, ...]
    min_confidence: float = 0.7,
) -> list[UIElement]:
    """
    Run RapidOCR on each dirty region from frame and return text UIElements.

    Args:
        frame:          CaptureFrame whose data will be cropped per region.
        regions:        Dirty regions from FrameDiff.dirty_regions.
                        Pass (frame.window_bbox,) to scan the whole window.
        min_confidence: Minimum OCR confidence to include a result.

    Returns:
        List of UIElement(source=OCR, element_type=TEXT) for detected text.

    Raises:
        PerceptionError(E202) if rapidocr_onnxruntime is not installed.
    """
    if not regions:
        return []

    ocr = _get_ocr()
    elements: list[UIElement] = []

    for region in regions:
        # Clamp region to frame dimensions before cropping
        x1 = max(0, region.x)
        y1 = max(0, region.y)
        x2 = min(frame.width, region.x + region.w)
        y2 = min(frame.height, region.y + region.h)
        if x2 <= x1 or y2 <= y1:
            continue

        crop = _bgra_to_bgr(frame.data[y1:y2, x1:x2])
        if crop.size == 0:
            continue

        try:
            result, _ = ocr(crop)
            elements.extend(
                _parse_rapid_result(result, x1, y1, frame.frame_id, min_confidence)
            )
        except Exception as e:
            raise PerceptionError(
                ErrorCode.PERCEPTION_TIMEOUT,
                f"RapidOCR failed on region {region}: {e}",
                {"region": (region.x, region.y, region.w, region.h)},
            ) from e

    return elements
