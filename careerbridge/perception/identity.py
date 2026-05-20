# identity.py — Phase 4/5: Visual element identity via perceptual hashing
# SCHEMA_VERSION: 1
#
# Single responsibility: compute a perceptual hash of a UI element's pixel
# region within a frame. Used to recognise the same visual element across
# frames even when its text or bbox shifts slightly.
#
# Does NOT modify UIElement (schema is frozen). Returns hash strings for
# callers to store and compare.

from __future__ import annotations

import numpy as np

from ..capture import CaptureFrame
from ..schema import BoundingBox, UIElement

try:
    from PIL import Image as _Image
    import imagehash as _imagehash
    _IMAGEHASH_AVAILABLE = True
except Exception:
    _IMAGEHASH_AVAILABLE = False

# Default hash size: 8 → 64-bit hash, fast and sufficient for UI elements.
_HASH_SIZE: int = 8


def _crop_element(frame: CaptureFrame, bbox: BoundingBox) -> "np.ndarray":
    """
    Crop element region from frame data.
    Clamps to frame dimensions; returns BGR uint8 array (h, w, 3).
    Returns None if the cropped region is degenerate.
    """
    x1 = max(0, bbox.x)
    y1 = max(0, bbox.y)
    x2 = min(frame.width, bbox.x + bbox.w)
    y2 = min(frame.height, bbox.y + bbox.h)
    if x2 <= x1 or y2 <= y1:
        return None
    # BGRA → drop alpha → grayscale-friendly for hashing
    return frame.data[y1:y2, x1:x2, :3]


def compute_element_phash(
    frame: CaptureFrame,
    element: UIElement,
    hash_size: int = _HASH_SIZE,
) -> str:
    """
    Compute a perceptual hash of the element's pixel region in frame.

    Returns a hex string (e.g. "f8f0e0c080808080").
    Returns "" if imagehash/Pillow is unavailable or the region is degenerate.

    Use for cross-frame identity matching: two elements with the same phash
    are visually identical even if their bbox or text differs slightly.
    """
    if not _IMAGEHASH_AVAILABLE:
        return ""

    crop = _crop_element(frame, element.bbox)
    if crop is None or crop.size == 0:
        return ""

    try:
        img = _Image.fromarray(crop[:, :, ::-1])  # BGR → RGB for PIL
        h = _imagehash.phash(img, hash_size=hash_size)
        return str(h)
    except Exception:
        return ""


def phash_distance(hash_a: str, hash_b: str) -> int:
    """
    Hamming distance between two phash hex strings.
    Returns 0 for identical, higher for more different.
    Returns 64 (max) if either string is empty or unparseable.
    """
    if not hash_a or not hash_b or not _IMAGEHASH_AVAILABLE:
        return 64
    try:
        ha = _imagehash.hex_to_hash(hash_a)
        hb = _imagehash.hex_to_hash(hash_b)
        return ha - hb
    except Exception:
        return 64


def elements_visually_match(
    hash_a: str,
    hash_b: str,
    threshold: int = 10,
) -> bool:
    """
    Return True if two element phashes are close enough to be the same element.
    Default threshold=10 allows minor rendering differences (antialiasing, scale).
    """
    return bool(phash_distance(hash_a, hash_b) <= threshold)
