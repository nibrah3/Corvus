# test_phase3.py — Phase 3: Frame Differencing Engine
# SCHEMA_VERSION: 1
#
# All tests are unit (pure numpy, no hardware).
# Covers: diff mask, tile grid, region merge, change classifier, public API,
#         edge cases, stress (large frames), shape mismatch error path.

from __future__ import annotations

import time

import numpy as np
import pytest

from careerbridge.capture import CaptureFrame
from careerbridge.errors import ErrorCode, PerceptionError
from careerbridge.perception.frame_diff import (
    DIFF_THRESHOLD,
    DIRTY_TILE_FRACTION,
    TILE_SIZE,
    FrameDiff,
    _build_diff_mask,
    _classify,
    _merge_dirty_tiles,
    _tile_dirty_grid,
    compute_diff,
)
from careerbridge.schema import BoundingBox
from careerbridge.types import ChangeType


# ── Test helpers ──────────────────────────────────────────────────────────────

def _bgra(h: int, w: int, fill: int = 0) -> np.ndarray:
    """Solid-colour BGRA frame data."""
    arr = np.full((h, w, 4), fill, dtype=np.uint8)
    return arr


def _frame(data: np.ndarray, frame_id: int = 0) -> CaptureFrame:
    h, w = data.shape[:2]
    bbox = BoundingBox(x=0, y=0, w=w, h=h)
    return CaptureFrame(
        frame_id=frame_id,
        timestamp=time.monotonic(),
        data=data,
        window_title="Test",
        window_bbox=bbox,
        region=None,
        backend=__import__("careerbridge.capture", fromlist=["CaptureBackend"]).CaptureBackend.MSS,
    )


def _frame_pair(h: int = 64, w: int = 64):
    """Two identical black frames."""
    a = _frame(_bgra(h, w, 0), frame_id=0)
    b = _frame(_bgra(h, w, 0), frame_id=1)
    return a, b


# ── FrameDiff validation ──────────────────────────────────────────────────────

class TestFrameDiffValidation:
    def test_valid_diff_constructs(self):
        d = FrameDiff(
            frame_a_id=0, frame_b_id=1,
            timestamp=time.monotonic(),
            change_type=ChangeType.NONE,
            changed_fraction=0.0,
            dirty_regions=(),
        )
        assert d.change_type == ChangeType.NONE

    def test_changed_fraction_above_one_rejected(self):
        with pytest.raises(ValueError, match="0.0–1.0"):
            FrameDiff(
                frame_a_id=0, frame_b_id=1,
                timestamp=1.0,
                change_type=ChangeType.NONE,
                changed_fraction=1.1,
                dirty_regions=(),
            )

    def test_negative_fraction_rejected(self):
        with pytest.raises(ValueError, match="0.0–1.0"):
            FrameDiff(
                frame_a_id=0, frame_b_id=1,
                timestamp=1.0,
                change_type=ChangeType.NONE,
                changed_fraction=-0.01,
                dirty_regions=(),
            )

    def test_dirty_regions_must_be_tuple(self):
        with pytest.raises(TypeError, match="tuple"):
            FrameDiff(
                frame_a_id=0, frame_b_id=1,
                timestamp=1.0,
                change_type=ChangeType.NONE,
                changed_fraction=0.0,
                dirty_regions=[],   # list not allowed
            )

    def test_fraction_zero_valid(self):
        d = FrameDiff(0, 1, 1.0, ChangeType.NONE, 0.0, ())
        assert d.changed_fraction == 0.0

    def test_fraction_one_valid(self):
        d = FrameDiff(0, 1, 1.0, ChangeType.STRUCTURAL, 1.0, ())
        assert d.changed_fraction == 1.0


# ── _build_diff_mask ──────────────────────────────────────────────────────────

class TestBuildDiffMask:
    def test_identical_frames_all_false(self):
        a = _bgra(32, 32, 100)
        mask = _build_diff_mask(a, a.copy(), threshold=30)
        assert not mask.any()

    def test_fully_changed_all_true(self):
        a = _bgra(16, 16, 0)
        b = _bgra(16, 16, 255)
        mask = _build_diff_mask(a, b, threshold=30)
        assert mask.all()

    def test_threshold_boundary_below_not_flagged(self):
        a = _bgra(8, 8, 100)
        b = _bgra(8, 8, 100 + 30)  # diff == threshold, not > threshold
        mask = _build_diff_mask(a, b, threshold=30)
        assert not mask.any()

    def test_threshold_boundary_above_flagged(self):
        a = _bgra(8, 8, 100)
        b = _bgra(8, 8, 100 + 31)  # diff == 31 > 30
        mask = _build_diff_mask(a, b, threshold=30)
        assert mask.all()

    def test_partial_change(self):
        a = _bgra(16, 16, 0)
        b = a.copy()
        b[0:8, 0:8] = 200  # top-left quadrant changed
        mask = _build_diff_mask(a, b, threshold=30)
        # Top-left quadrant True, rest False
        assert mask[0:8, 0:8].all()
        assert not mask[8:, :].any()
        assert not mask[:, 8:].any()

    def test_single_channel_change_detected(self):
        """Only the B channel differs — should still flag the pixel."""
        a = np.zeros((4, 4, 4), dtype=np.uint8)
        b = a.copy()
        b[2, 2, 0] = 200  # B channel only
        mask = _build_diff_mask(a, b, threshold=30)
        assert mask[2, 2]
        assert not mask[0, 0]

    def test_alpha_channel_change_detected(self):
        a = np.zeros((4, 4, 4), dtype=np.uint8)
        b = a.copy()
        b[1, 1, 3] = 200  # alpha channel
        mask = _build_diff_mask(a, b, threshold=30)
        assert mask[1, 1]

    def test_no_uint8_wraparound(self):
        """255 - 0 must give 255, not 1 (uint8 wrap)."""
        a = _bgra(4, 4, 0)
        b = _bgra(4, 4, 255)
        mask = _build_diff_mask(a, b, threshold=30)
        assert mask.all()

    def test_output_shape_matches_input(self):
        a = _bgra(48, 80, 0)
        b = _bgra(48, 80, 0)
        mask = _build_diff_mask(a, b, threshold=30)
        assert mask.shape == (48, 80)

    def test_output_dtype_is_bool(self):
        a = _bgra(8, 8, 0)
        mask = _build_diff_mask(a, a.copy(), threshold=30)
        assert mask.dtype == bool


# ── _tile_dirty_grid ─────────────────────────────────────────────────────────

class TestTileDirtyGrid:
    def test_clean_mask_gives_all_false_grid(self):
        mask = np.zeros((64, 64), dtype=bool)
        grid = _tile_dirty_grid(mask, tile_size=16, dirty_fraction=0.05)
        assert not grid.any()

    def test_fully_dirty_mask_gives_all_true_grid(self):
        mask = np.ones((64, 64), dtype=bool)
        grid = _tile_dirty_grid(mask, tile_size=16, dirty_fraction=0.05)
        assert grid.all()

    def test_grid_dimensions_exact_division(self):
        mask = np.zeros((64, 96), dtype=bool)
        grid = _tile_dirty_grid(mask, tile_size=16, dirty_fraction=0.05)
        assert grid.shape == (4, 6)

    def test_grid_dimensions_partial_tiles(self):
        # 70 rows → (70+15)//16 = 5 tile rows; 90 cols → (90+15)//16 = 6 cols
        mask = np.zeros((70, 90), dtype=bool)
        grid = _tile_dirty_grid(mask, tile_size=16, dirty_fraction=0.05)
        assert grid.shape == (5, 6)

    def test_exactly_at_dirty_fraction_not_flagged(self):
        # tile 8x8=64 pixels, 5% = 3.2 pixels → need >3.2, i.e. ≥4
        mask = np.zeros((8, 8), dtype=bool)
        mask[0, 0] = True  # 1/64 = 1.56% — tile 0.0156 < 0.05 → not dirty
        grid = _tile_dirty_grid(mask, tile_size=8, dirty_fraction=0.05)
        assert not grid[0, 0]

    def test_above_dirty_fraction_flagged(self):
        # Set 10% of a 10x10 tile (need >5%)
        mask = np.zeros((10, 10), dtype=bool)
        mask[0, :] = True  # 10/100 = 10% > 5%
        grid = _tile_dirty_grid(mask, tile_size=10, dirty_fraction=0.05)
        assert grid[0, 0]

    def test_only_specific_tile_dirty(self):
        mask = np.zeros((32, 32), dtype=bool)
        # Dirty only tile (1,1): rows 16-31, cols 16-31
        mask[16:32, 16:32] = True
        grid = _tile_dirty_grid(mask, tile_size=16, dirty_fraction=0.05)
        assert grid[1, 1]
        assert not grid[0, 0]
        assert not grid[0, 1]
        assert not grid[1, 0]


# ── _merge_dirty_tiles ────────────────────────────────────────────────────────

class TestMergeDirtyTiles:
    def test_empty_grid_returns_empty_tuple(self):
        grid = np.zeros((4, 4), dtype=bool)
        result = _merge_dirty_tiles(grid, tile_size=16, frame_w=64, frame_h=64)
        assert result == ()

    def test_single_tile_correct_bbox(self):
        grid = np.zeros((4, 4), dtype=bool)
        grid[0, 0] = True
        result = _merge_dirty_tiles(grid, tile_size=16, frame_w=64, frame_h=64)
        assert len(result) == 1
        assert result[0] == BoundingBox(x=0, y=0, w=16, h=16)

    def test_two_disconnected_tiles_two_regions(self):
        grid = np.zeros((4, 4), dtype=bool)
        grid[0, 0] = True
        grid[3, 3] = True
        result = _merge_dirty_tiles(grid, tile_size=16, frame_w=64, frame_h=64)
        assert len(result) == 2

    def test_adjacent_tiles_merge_into_one_region(self):
        grid = np.zeros((4, 4), dtype=bool)
        grid[0, 0] = True
        grid[0, 1] = True  # horizontally adjacent
        result = _merge_dirty_tiles(grid, tile_size=16, frame_w=64, frame_h=64)
        assert len(result) == 1
        assert result[0].w == 32  # two tiles wide

    def test_vertical_adjacent_tiles_merge(self):
        grid = np.zeros((4, 4), dtype=bool)
        grid[0, 0] = True
        grid[1, 0] = True
        result = _merge_dirty_tiles(grid, tile_size=16, frame_w=64, frame_h=64)
        assert len(result) == 1
        assert result[0].h == 32

    def test_l_shape_merges_to_bounding_box(self):
        grid = np.zeros((4, 4), dtype=bool)
        grid[0, 0] = True
        grid[1, 0] = True
        grid[1, 1] = True  # L-shape
        result = _merge_dirty_tiles(grid, tile_size=16, frame_w=64, frame_h=64)
        assert len(result) == 1
        assert result[0].w == 32
        assert result[0].h == 32

    def test_full_grid_single_region(self):
        grid = np.ones((4, 4), dtype=bool)
        result = _merge_dirty_tiles(grid, tile_size=16, frame_w=64, frame_h=64)
        assert len(result) == 1
        assert result[0] == BoundingBox(x=0, y=0, w=64, h=64)

    def test_edge_tile_clamped_to_frame(self):
        # Frame is 70x70, tile_size=16 → partial tiles at edges
        # Grid shape will be (5, 5). Last tile at (4,4): pixel 64–70
        grid = np.zeros((5, 5), dtype=bool)
        grid[4, 4] = True  # bottom-right partial tile
        result = _merge_dirty_tiles(grid, tile_size=16, frame_w=70, frame_h=70)
        assert len(result) == 1
        r = result[0]
        assert r.x == 64
        assert r.y == 64
        assert r.w == 6   # 70 - 64
        assert r.h == 6

    def test_returns_tuple_not_list(self):
        grid = np.zeros((2, 2), dtype=bool)
        result = _merge_dirty_tiles(grid, tile_size=16, frame_w=32, frame_h=32)
        assert isinstance(result, tuple)


# ── _classify ─────────────────────────────────────────────────────────────────

class TestClassify:
    def test_zero_fraction_is_none(self):
        assert _classify(0.0) == ChangeType.NONE

    def test_tiny_fraction_is_minor(self):
        assert _classify(0.001) == ChangeType.MINOR

    def test_below_minor_max_is_minor(self):
        assert _classify(0.0049) == ChangeType.MINOR

    def test_at_minor_max_is_content(self):
        assert _classify(0.005) == ChangeType.CONTENT

    def test_mid_content(self):
        assert _classify(0.05) == ChangeType.CONTENT

    def test_just_below_content_max(self):
        assert _classify(0.1499) == ChangeType.CONTENT

    def test_at_content_max_is_structural(self):
        assert _classify(0.15) == ChangeType.STRUCTURAL

    def test_full_frame_is_structural(self):
        assert _classify(1.0) == ChangeType.STRUCTURAL


# ── compute_diff (public API) ─────────────────────────────────────────────────

class TestComputeDiff:
    def test_identical_frames_gives_none(self):
        data = _bgra(64, 64, 128)
        fa, fb = _frame(data, 0), _frame(data.copy(), 1)
        diff = compute_diff(fa, fb)
        assert diff.change_type == ChangeType.NONE
        assert diff.changed_fraction == 0.0
        assert diff.dirty_regions == ()

    def test_fully_changed_gives_structural(self):
        fa = _frame(_bgra(64, 64, 0), 0)
        fb = _frame(_bgra(64, 64, 255), 1)
        diff = compute_diff(fa, fb)
        assert diff.change_type == ChangeType.STRUCTURAL
        assert diff.changed_fraction == 1.0

    def test_small_change_classified_minor(self):
        data = _bgra(100, 100, 0)
        changed = data.copy()
        # Change a single 2x2 pixel block — very small fraction
        changed[0:2, 0:2] = 200
        fa = _frame(data, 0)
        fb = _frame(changed, 1)
        diff = compute_diff(fa, fb)
        assert diff.change_type == ChangeType.MINOR

    def test_moderate_change_classified_content(self):
        data = _bgra(100, 100, 0)
        changed = data.copy()
        # Change ~10% of pixels (10 rows out of 100)
        changed[0:10, :] = 200
        fa = _frame(data, 0)
        fb = _frame(changed, 1)
        diff = compute_diff(fa, fb)
        assert diff.change_type == ChangeType.CONTENT

    def test_frame_ids_stored_correctly(self):
        fa = _frame(_bgra(32, 32, 0), frame_id=7)
        fb = _frame(_bgra(32, 32, 0), frame_id=42)
        diff = compute_diff(fa, fb)
        assert diff.frame_a_id == 7
        assert diff.frame_b_id == 42

    def test_shape_mismatch_raises_perception_error(self):
        fa = _frame(_bgra(64, 64, 0), 0)
        fb = _frame(_bgra(32, 64, 0), 1)
        with pytest.raises(PerceptionError) as exc:
            compute_diff(fa, fb)
        assert exc.value.code == ErrorCode.PERCEPTION_SHAPE_MISMATCH

    def test_error_carries_frame_ids_in_context(self):
        fa = _frame(_bgra(64, 64, 0), frame_id=5)
        fb = _frame(_bgra(32, 64, 0), frame_id=9)
        with pytest.raises(PerceptionError) as exc:
            compute_diff(fa, fb)
        assert exc.value.context["frame_a_id"] == 5
        assert exc.value.context["frame_b_id"] == 9

    def test_timestamp_positive(self):
        fa, fb = _frame_pair()
        diff = compute_diff(fa, fb)
        assert diff.timestamp > 0.0

    def test_dirty_regions_cover_changed_area(self):
        data = _bgra(64, 64, 0)
        changed = data.copy()
        # Change bottom-right quadrant
        changed[32:, 32:] = 200
        fa = _frame(data, 0)
        fb = _frame(changed, 1)
        diff = compute_diff(fa, fb)
        assert len(diff.dirty_regions) >= 1
        # At least one region should overlap the changed area
        changed_area = BoundingBox(x=32, y=32, w=32, h=32)
        overlaps = any(
            r.x < changed_area.x + changed_area.w
            and r.x + r.w > changed_area.x
            and r.y < changed_area.y + changed_area.h
            and r.y + r.h > changed_area.y
            for r in diff.dirty_regions
        )
        assert overlaps

    def test_no_dirty_regions_when_no_change(self):
        fa, fb = _frame_pair()
        diff = compute_diff(fa, fb)
        assert diff.dirty_regions == ()

    def test_returns_frame_diff_instance(self):
        fa, fb = _frame_pair()
        assert isinstance(compute_diff(fa, fb), FrameDiff)

    def test_custom_threshold_respected(self):
        data = _bgra(16, 16, 100)
        changed = data.copy()
        changed[:] = 115  # diff = 15
        fa = _frame(data, 0)
        fb = _frame(changed, 1)
        # With threshold=30, diff=15 should not flag anything
        diff_high = compute_diff(fa, fb, threshold=30)
        assert diff_high.change_type == ChangeType.NONE
        # With threshold=10, diff=15 should flag everything
        diff_low = compute_diff(fa, fb, threshold=10)
        assert diff_low.change_type == ChangeType.STRUCTURAL


# ── Edge cases ────────────────────────────────────────────────────────────────

class TestEdgeCases:
    def test_single_pixel_frame(self):
        fa = _frame(_bgra(1, 1, 0), 0)
        fb = _frame(_bgra(1, 1, 255), 1)
        diff = compute_diff(fa, fb)
        assert diff.change_type == ChangeType.STRUCTURAL
        assert diff.changed_fraction == 1.0

    def test_non_square_frame(self):
        fa = _frame(_bgra(480, 1280, 0), 0)
        fb = _frame(_bgra(480, 1280, 0), 1)
        diff = compute_diff(fa, fb)
        assert diff.change_type == ChangeType.NONE

    def test_frame_height_not_divisible_by_tile(self):
        # 70 rows, tile=16 — partial bottom row of tiles
        data = _bgra(70, 64, 0)
        fa = _frame(data, 0)
        fb = _frame(data.copy(), 1)
        diff = compute_diff(fa, fb)
        assert diff.change_type == ChangeType.NONE

    def test_multiple_isolated_regions(self):
        data = _bgra(64, 64, 0)
        changed = data.copy()
        # Two isolated 16x16 blobs in opposite corners
        changed[0:16, 0:16] = 200
        changed[48:64, 48:64] = 200
        fa = _frame(data, 0)
        fb = _frame(changed, 1)
        diff = compute_diff(fa, fb)
        # Should produce two separate dirty regions
        assert len(diff.dirty_regions) == 2

    def test_symmetric_diff_same_fraction(self):
        """compute_diff(a,b) and compute_diff(b,a) should give same changed_fraction."""
        fa = _frame(_bgra(32, 32, 0), 0)
        fb = _frame(_bgra(32, 32, 200), 1)
        d_ab = compute_diff(fa, fb)
        d_ba = compute_diff(fb, fa)
        assert d_ab.changed_fraction == d_ba.changed_fraction


# ── Stress: large frame ───────────────────────────────────────────────────────

class TestStress:
    def test_full_hd_diff_completes(self):
        """1080p diff must complete in under 2 seconds (CPU only)."""
        import time as _time
        fa = _frame(_bgra(1080, 1920, 0), 0)
        fb = _frame(_bgra(1080, 1920, 128), 1)
        t0 = _time.perf_counter()
        diff = compute_diff(fa, fb)
        elapsed = _time.perf_counter() - t0
        assert elapsed < 2.0, f"1080p diff took {elapsed:.2f}s"
        assert diff.change_type == ChangeType.STRUCTURAL

    def test_100_diffs_no_error(self):
        """Repeated diffing must not accumulate state or raise."""
        fa = _frame(_bgra(64, 64, 0), 0)
        for i in range(1, 101):
            fb = _frame(_bgra(64, 64, i % 256), i)
            compute_diff(fa, fb)
            fa = fb
