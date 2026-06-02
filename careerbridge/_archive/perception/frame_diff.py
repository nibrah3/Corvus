# frame_diff.py — Phase 3: Frame Differencing Engine
# SCHEMA_VERSION: 1
#
# Single responsibility: compare two CaptureFrames and describe what changed.
#
# Outputs: FrameDiff — change type, changed fraction, dirty pixel regions.
# MUST NOT: interpret content, run OCR, make navigation decisions.
#
# Algorithm:
#   1. Per-pixel absolute channel difference → binary change mask
#   2. Tile the mask (16×16 px), mark dirty tiles by fraction threshold
#   3. BFS-merge connected dirty tiles → pixel BoundingBox regions
#   4. Classify change magnitude by fraction of changed pixels

from __future__ import annotations

import time
from dataclasses import dataclass

import numpy as np

from ..capture import CaptureFrame
from ..errors import ErrorCode, PerceptionError
from ..schema import BoundingBox
from ..types import ChangeType

# ── Tunable constants ─────────────────────────────────────────────────────────

DIFF_THRESHOLD: int = 30          # per-channel absolute diff to count pixel as changed
TILE_SIZE: int = 16               # tile dimension in pixels (square)
DIRTY_TILE_FRACTION: float = 0.05 # fraction of tile pixels that must change to mark tile dirty

# ChangeType thresholds (fraction of total frame pixels)
_MINOR_MAX: float = 0.005   # below this → MINOR
_CONTENT_MAX: float = 0.15  # below this → CONTENT, at/above → STRUCTURAL


# ── FrameDiff dataclass ───────────────────────────────────────────────────────

@dataclass(frozen=True)
class FrameDiff:
    """
    Result of comparing two consecutive CaptureFrames.

    frame_a_id:       frame_id of the earlier frame.
    frame_b_id:       frame_id of the later frame.
    timestamp:        time.monotonic() at diff computation time.
    change_type:      NONE / MINOR / CONTENT / STRUCTURAL.
    changed_fraction: fraction of pixels that changed (0.0–1.0).
    dirty_regions:    merged pixel BoundingBoxes of changed areas (may be empty).
    """
    frame_a_id:       int
    frame_b_id:       int
    timestamp:        float
    change_type:      ChangeType
    changed_fraction: float
    dirty_regions:    tuple  # tuple[BoundingBox, ...]

    def __post_init__(self) -> None:
        if not 0.0 <= self.changed_fraction <= 1.0:
            raise ValueError(
                f"FrameDiff.changed_fraction must be 0.0–1.0, got {self.changed_fraction}"
            )
        if not isinstance(self.dirty_regions, tuple):
            raise TypeError(
                f"FrameDiff.dirty_regions must be a tuple, got {type(self.dirty_regions)}"
            )


# ── Internal helpers ──────────────────────────────────────────────────────────

def _build_diff_mask(
    data_a: np.ndarray,
    data_b: np.ndarray,
    threshold: int,
) -> np.ndarray:
    """
    Return bool (h, w) mask — True where any BGRA channel differs by > threshold.
    Uses int16 intermediate to avoid uint8 wrap-around.
    """
    delta = np.abs(data_a.astype(np.int16) - data_b.astype(np.int16))
    return np.max(delta, axis=2) > threshold


def _tile_dirty_grid(
    mask: np.ndarray,
    tile_size: int,
    dirty_fraction: float,
) -> np.ndarray:
    """
    Divide bool mask into tile_size×tile_size tiles.
    Return bool grid (grid_rows, grid_cols): True where tile changed fraction > dirty_fraction.
    Partial edge tiles are included.
    """
    h, w = mask.shape
    grid_rows = (h + tile_size - 1) // tile_size
    grid_cols = (w + tile_size - 1) // tile_size
    grid = np.zeros((grid_rows, grid_cols), dtype=bool)

    for r in range(grid_rows):
        for c in range(grid_cols):
            tile = mask[
                r * tile_size : (r + 1) * tile_size,
                c * tile_size : (c + 1) * tile_size,
            ]
            if tile.mean() > dirty_fraction:
                grid[r, c] = True

    return grid


def _merge_dirty_tiles(
    grid: np.ndarray,
    tile_size: int,
    frame_w: int,
    frame_h: int,
) -> tuple:
    """
    BFS-merge 4-connected dirty tiles into pixel-space BoundingBox objects.
    Returns tuple[BoundingBox, ...], empty if no dirty tiles.
    """
    if not grid.any():
        return ()

    visited = np.zeros_like(grid, dtype=bool)
    regions: list[BoundingBox] = []
    grid_rows, grid_cols = grid.shape
    _DIRS = ((-1, 0), (1, 0), (0, -1), (0, 1))

    for r in range(grid_rows):
        for c in range(grid_cols):
            if not grid[r, c] or visited[r, c]:
                continue

            queue = [(r, c)]
            visited[r, c] = True
            min_r = max_r = r
            min_c = max_c = c

            while queue:
                cr, cc = queue.pop()
                if cr < min_r: min_r = cr
                if cr > max_r: max_r = cr
                if cc < min_c: min_c = cc
                if cc > max_c: max_c = cc
                for dr, dc in _DIRS:
                    nr, nc = cr + dr, cc + dc
                    if (0 <= nr < grid_rows and 0 <= nc < grid_cols
                            and grid[nr, nc] and not visited[nr, nc]):
                        visited[nr, nc] = True
                        queue.append((nr, nc))

            px = min_c * tile_size
            py = min_r * tile_size
            pw = min((max_c + 1) * tile_size, frame_w) - px
            ph = min((max_r + 1) * tile_size, frame_h) - py
            regions.append(BoundingBox(x=px, y=py, w=pw, h=ph))

    return tuple(regions)


def _classify(changed_fraction: float) -> ChangeType:
    if changed_fraction == 0.0:
        return ChangeType.NONE
    if changed_fraction < _MINOR_MAX:
        return ChangeType.MINOR
    if changed_fraction < _CONTENT_MAX:
        return ChangeType.CONTENT
    return ChangeType.STRUCTURAL


# ── Public API ────────────────────────────────────────────────────────────────

def compute_diff(
    frame_a: CaptureFrame,
    frame_b: CaptureFrame,
    threshold: int = DIFF_THRESHOLD,
    tile_size: int = TILE_SIZE,
    dirty_tile_fraction: float = DIRTY_TILE_FRACTION,
) -> FrameDiff:
    """
    Compare two CaptureFrames and return a FrameDiff.

    Args:
        frame_a:             Earlier frame.
        frame_b:             Later frame.
        threshold:           Per-channel absolute diff to count a pixel as changed.
        tile_size:           Tile dimension in pixels for region grouping.
        dirty_tile_fraction: Fraction of changed pixels needed to mark a tile dirty.

    Returns:
        FrameDiff with classification, changed fraction, and dirty region list.

    Raises:
        PerceptionError(E205) if frames have different pixel shapes.
    """
    if frame_a.data.shape != frame_b.data.shape:
        raise PerceptionError(
            ErrorCode.PERCEPTION_SHAPE_MISMATCH,
            f"Frame shapes differ: {frame_a.data.shape} vs {frame_b.data.shape}",
            {"frame_a_id": frame_a.frame_id, "frame_b_id": frame_b.frame_id},
        )

    mask = _build_diff_mask(frame_a.data, frame_b.data, threshold)
    total_pixels = mask.size
    changed_fraction = float(mask.sum()) / total_pixels if total_pixels > 0 else 0.0

    grid = _tile_dirty_grid(mask, tile_size, dirty_tile_fraction)
    dirty_regions = _merge_dirty_tiles(grid, tile_size, frame_b.width, frame_b.height)

    return FrameDiff(
        frame_a_id=frame_a.frame_id,
        frame_b_id=frame_b.frame_id,
        timestamp=time.monotonic(),
        change_type=_classify(changed_fraction),
        changed_fraction=changed_fraction,
        dirty_regions=dirty_regions,
    )
