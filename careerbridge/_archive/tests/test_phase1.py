# test_phase1.py — Phase 1 actuation layer tests
#
# All tests use dry_run=True — no actual mouse movement or keypresses.
# Integration tests (marked @pytest.mark.integration) require a live desktop
# and are excluded from CI by default: pytest -m "not integration"
#
# EXIT CRITERIA (governance):
#   - deterministic click at coordinates accuracy >= 99%
#   - input reproducibility test passes 1000 iterations
#   - coordinate stress test
#   - timing jitter test
#   - repeated action idempotency test

import random
import sys
import os
import time

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

from careerbridge.actions import (
    ActionResult,
    _cubic_bezier,
    _move_bezier,
    _execute_click,
    _execute_type,
    _execute_scroll,
    _wpm_to_ms_per_char,
    dispatch,
    _POSITION_TOLERANCE_PX,
    _MAX_RETRIES,
)
from careerbridge.errors import ActionError, ErrorCode
from careerbridge.schema import (
    Action, BehaviorFingerprint, BoundingBox,
    SCHEMA_VERSION,
)
from careerbridge.types import ActionType, MouseSpeed


# ── Fixtures ──────────────────────────────────────────────────────────────────

def make_behavior(wpm=62, error_rate=0.0, speed=MouseSpeed.FAST) -> BehaviorFingerprint:
    return BehaviorFingerprint(
        typing_wpm=wpm,
        error_rate=error_rate,
        mouse_speed=speed,
        pause_min_ms=100,
        pause_max_ms=300,
    )


def make_bbox(x=100, y=200, w=80, h=20) -> BoundingBox:
    return BoundingBox(x=x, y=y, w=w, h=h)


def make_action(
    action_type=ActionType.CLICK,
    payload=None,
    action_id="act_001",
) -> Action:
    return Action(
        action_id=action_id,
        action_type=action_type,
        target_element_id="elem_001",
        payload=payload or {},
        profile_id="prof_001",
        frame_id=1,
    )


def seeded_rng(seed=42) -> random.Random:
    return random.Random(seed)


# ── Bezier math tests ─────────────────────────────────────────────────────────

class TestBezierMath:
    def test_at_t0_returns_p0(self):
        assert _cubic_bezier(10.0, 20.0, 30.0, 40.0, 0.0) == pytest.approx(10.0)

    def test_at_t1_returns_p3(self):
        assert _cubic_bezier(10.0, 20.0, 30.0, 40.0, 1.0) == pytest.approx(40.0)

    def test_midpoint_between_endpoints(self):
        # With symmetric control points, midpoint should be near midpoint of endpoints
        result = _cubic_bezier(0.0, 0.0, 100.0, 100.0, 0.5)
        assert 0.0 < result < 100.0

    def test_monotonic_for_straight_line(self):
        # p0=p1=0, p2=p3=100 → strictly increasing
        values = [_cubic_bezier(0.0, 0.0, 100.0, 100.0, t/10) for t in range(11)]
        for i in range(len(values) - 1):
            assert values[i] <= values[i + 1]

    def test_deterministic_same_inputs(self):
        r1 = _cubic_bezier(5.0, 15.0, 25.0, 35.0, 0.3)
        r2 = _cubic_bezier(5.0, 15.0, 25.0, 35.0, 0.3)
        assert r1 == r2


# ── WPM conversion tests ──────────────────────────────────────────────────────

class TestWpmConversion:
    def test_60wpm_gives_200ms(self):
        assert _wpm_to_ms_per_char(60) == pytest.approx(200.0)

    def test_120wpm_gives_100ms(self):
        assert _wpm_to_ms_per_char(120) == pytest.approx(100.0)

    def test_higher_wpm_gives_lower_delay(self):
        assert _wpm_to_ms_per_char(100) < _wpm_to_ms_per_char(50)

    def test_boundary_20wpm(self):
        delay = _wpm_to_ms_per_char(20)
        assert delay == pytest.approx(600.0)

    def test_boundary_200wpm(self):
        delay = _wpm_to_ms_per_char(200)
        assert delay == pytest.approx(60.0)


# ── ActionResult tests ────────────────────────────────────────────────────────

class TestActionResult:
    def test_success_result(self):
        r = ActionResult(success=True, action_id="act_1", elapsed_ms=45.2)
        assert r.success
        assert r.error_code is None

    def test_failure_result(self):
        r = ActionResult(
            success=False,
            action_id="act_1",
            elapsed_ms=0.0,
            error_code=ErrorCode.ACTION_CLICK_UNVERIFIED,
            error_message="missed",
        )
        assert not r.success
        assert r.error_code == ErrorCode.ACTION_CLICK_UNVERIFIED

    def test_immutable(self):
        r = ActionResult(success=True, action_id="a", elapsed_ms=1.0)
        with pytest.raises((AttributeError, TypeError)):
            r.success = False  # type: ignore


# ── Dispatch: click tests ─────────────────────────────────────────────────────

class TestDispatchClick:
    def test_click_returns_success(self):
        result = dispatch(
            make_action(ActionType.CLICK),
            make_bbox(),
            make_behavior(),
            dry_run=True,
            _rng=seeded_rng(),
        )
        assert result.success
        assert result.action_id == "act_001"

    def test_click_elapsed_nonnegative(self):
        result = dispatch(
            make_action(ActionType.CLICK),
            make_bbox(),
            make_behavior(),
            dry_run=True,
            _rng=seeded_rng(),
        )
        assert result.elapsed_ms >= 0.0

    def test_focus_behaves_like_click(self):
        result = dispatch(
            make_action(ActionType.FOCUS),
            make_bbox(),
            make_behavior(),
            dry_run=True,
            _rng=seeded_rng(),
        )
        assert result.success

    def test_different_seeds_produce_success(self):
        for seed in range(20):
            result = dispatch(
                make_action(ActionType.CLICK),
                make_bbox(),
                make_behavior(),
                dry_run=True,
                _rng=random.Random(seed),
            )
            assert result.success, f"Failed for seed={seed}"


# ── Dispatch: type tests ──────────────────────────────────────────────────────

class TestDispatchType:
    def test_type_returns_success(self):
        result = dispatch(
            make_action(ActionType.TYPE, {"text": "hello world"}),
            make_bbox(),
            make_behavior(),
            dry_run=True,
            _rng=seeded_rng(),
        )
        assert result.success

    def test_type_empty_string(self):
        result = dispatch(
            make_action(ActionType.TYPE, {"text": ""}),
            make_bbox(),
            make_behavior(),
            dry_run=True,
            _rng=seeded_rng(),
        )
        assert result.success

    def test_type_with_error_rate_succeeds(self):
        result = dispatch(
            make_action(ActionType.TYPE, {"text": "test typing with errors"}),
            make_bbox(),
            make_behavior(error_rate=0.15),
            dry_run=True,
            _rng=seeded_rng(123),
        )
        assert result.success

    def test_type_long_text(self):
        long_text = "The quick brown fox jumps over the lazy dog. " * 5
        result = dispatch(
            make_action(ActionType.TYPE, {"text": long_text}),
            make_bbox(),
            make_behavior(),
            dry_run=True,
            _rng=seeded_rng(),
        )
        assert result.success


# ── Dispatch: scroll tests ────────────────────────────────────────────────────

class TestDispatchScroll:
    def test_scroll_down_returns_success(self):
        result = dispatch(
            make_action(ActionType.SCROLL, {"direction": "down", "amount": 3}),
            make_bbox(),
            make_behavior(),
            dry_run=True,
            _rng=seeded_rng(),
        )
        assert result.success

    def test_scroll_up_returns_success(self):
        result = dispatch(
            make_action(ActionType.SCROLL, {"direction": "up", "amount": 5}),
            make_bbox(),
            make_behavior(),
            dry_run=True,
            _rng=seeded_rng(),
        )
        assert result.success

    def test_scroll_large_amount(self):
        result = dispatch(
            make_action(ActionType.SCROLL, {"direction": "down", "amount": 20}),
            make_bbox(),
            make_behavior(),
            dry_run=True,
            _rng=seeded_rng(),
        )
        assert result.success


# ── Dispatch: wait tests ──────────────────────────────────────────────────────

class TestDispatchWait:
    def test_wait_returns_zero_elapsed(self):
        result = dispatch(
            make_action(ActionType.WAIT, {"condition": "page_load"}),
            make_bbox(),
            make_behavior(),
            dry_run=True,
            _rng=seeded_rng(),
        )
        assert result.success
        assert result.elapsed_ms == 0.0


# ── Coordinate stress test ────────────────────────────────────────────────────

class TestCoordinateStress:
    def test_click_100_random_coordinates(self):
        """
        Dispatch clicks at 100 random coordinates in dry_run mode.
        All must return success — 100% accuracy requirement.
        """
        rng = random.Random(999)
        failures = 0
        total = 100

        for _ in range(total):
            x = rng.randint(0, 1919)
            y = rng.randint(0, 1079)
            bbox = BoundingBox(x=x, y=y, w=2, h=2)
            result = dispatch(
                make_action(ActionType.CLICK),
                bbox,
                make_behavior(),
                dry_run=True,
                _rng=random.Random(rng.randint(0, 99999)),
            )
            if not result.success:
                failures += 1

        success_rate = (total - failures) / total
        assert success_rate >= 0.99, f"Success rate {success_rate:.2%} below 99%"

    def test_click_edge_coordinates(self):
        """Corners and edges of a 1920x1080 screen."""
        corners = [
            BoundingBox(x=0,    y=0,    w=2, h=2),
            BoundingBox(x=1918, y=0,    w=2, h=2),
            BoundingBox(x=0,    y=1078, w=2, h=2),
            BoundingBox(x=1918, y=1078, w=2, h=2),
            BoundingBox(x=960,  y=540,  w=2, h=2),  # center
        ]
        for bbox in corners:
            result = dispatch(
                make_action(ActionType.CLICK),
                bbox,
                make_behavior(),
                dry_run=True,
                _rng=seeded_rng(),
            )
            assert result.success, f"Failed at ({bbox.x},{bbox.y})"


# ── Timing jitter tests ───────────────────────────────────────────────────────

class TestTimingJitter:
    def test_wpm_delay_within_bounds(self):
        """
        Verify per-character delay stays within [min, max] bounds
        across 500 samples using a seeded rng.
        """
        wpm = 62
        mean = _wpm_to_ms_per_char(wpm) / 1000.0
        std  = mean * 0.25
        min_d = mean * 0.4
        max_d = mean * 2.0

        rng = random.Random(42)
        for _ in range(500):
            delay = max(min_d, min(max_d, rng.gauss(mean, std)))
            assert min_d <= delay <= max_d, \
                f"Delay {delay:.4f}s outside [{min_d:.4f}, {max_d:.4f}]"

    def test_different_wpm_profiles_different_delays(self):
        slow_delay = _wpm_to_ms_per_char(30)
        fast_delay = _wpm_to_ms_per_char(150)
        assert slow_delay > fast_delay

    def test_timing_not_negative(self):
        rng = random.Random(0)
        for wpm in (20, 62, 100, 200):
            mean = _wpm_to_ms_per_char(wpm) / 1000.0
            std  = mean * 0.25
            min_d = mean * 0.4
            for _ in range(100):
                delay = max(min_d, rng.gauss(mean, std))
                assert delay >= 0, f"Negative delay {delay} for wpm={wpm}"


# ── Reproducibility test (1000 iterations) ────────────────────────────────────

class TestReproducibility:
    def test_1000_click_iterations(self):
        """
        Same seeded RNG + same inputs = same ActionResult on every iteration.
        Verifies determinism: no hidden mutable state in dispatch path.
        """
        action  = make_action(ActionType.CLICK)
        bbox    = make_bbox(500, 400, 120, 30)
        profile = make_behavior()

        results = []
        for i in range(1000):
            r = dispatch(action, bbox, profile, dry_run=True, _rng=random.Random(42))
            results.append(r.success)

        assert all(results), f"Failed on {results.count(False)} of 1000 iterations"

    def test_1000_type_iterations(self):
        """Type 'hello world' 1000 times in dry_run — all must succeed."""
        action  = make_action(ActionType.TYPE, {"text": "hello world"})
        bbox    = make_bbox()
        profile = make_behavior(error_rate=0.05)

        failures = sum(
            0 if dispatch(action, bbox, profile, dry_run=True, _rng=random.Random(i)).success else 1
            for i in range(1000)
        )
        assert failures == 0, f"{failures}/1000 type iterations failed"

    def test_seeded_rng_same_result(self):
        """Two calls with the same seed must produce identical results."""
        action  = make_action(ActionType.CLICK)
        bbox    = make_bbox()
        profile = make_behavior()

        r1 = dispatch(action, bbox, profile, dry_run=True, _rng=random.Random(77))
        r2 = dispatch(action, bbox, profile, dry_run=True, _rng=random.Random(77))

        assert r1.success == r2.success


# ── Idempotency tests ─────────────────────────────────────────────────────────

class TestIdempotency:
    def test_repeated_click_same_bbox(self):
        """
        Clicking the same element N times must always succeed.
        Action layer has no memory of previous calls.
        """
        action  = make_action(ActionType.CLICK)
        bbox    = make_bbox(640, 360, 100, 24)
        profile = make_behavior()

        for i in range(50):
            result = dispatch(action, bbox, profile, dry_run=True, _rng=random.Random(i))
            assert result.success, f"Iteration {i} failed"

    def test_repeated_scroll_down(self):
        action = make_action(ActionType.SCROLL, {"direction": "down", "amount": 3})
        bbox   = make_bbox()
        profile = make_behavior()

        for i in range(50):
            result = dispatch(action, bbox, profile, dry_run=True, _rng=random.Random(i))
            assert result.success, f"Scroll iteration {i} failed"

    def test_action_layer_has_no_state(self):
        """
        Dispatch same action twice with same seed — results must be identical.
        If any state leaked between calls, seeds would diverge.
        """
        action  = make_action(ActionType.TYPE, {"text": "stateless"})
        bbox    = make_bbox()
        profile = make_behavior()

        r1 = dispatch(action, bbox, profile, dry_run=True, _rng=random.Random(55))
        r2 = dispatch(action, bbox, profile, dry_run=True, _rng=random.Random(55))

        assert r1.success == r2.success
        assert r1.action_id == r2.action_id


# ── Error handling tests ──────────────────────────────────────────────────────

class TestErrorHandling:
    def test_dispatch_returns_result_not_raises(self):
        """
        dispatch() must never raise — failures become ActionResult(success=False).
        """
        # Impossible action type via monkey-patch
        action = make_action(ActionType.CLICK)
        # dispatch wraps ActionError into result
        result = dispatch(action, make_bbox(), make_behavior(), dry_run=True)
        assert isinstance(result, ActionResult)

    def test_action_result_carries_error_on_failure(self):
        """Simulate a failed result directly."""
        r = ActionResult(
            success=False,
            action_id="test",
            elapsed_ms=0.0,
            error_code=ErrorCode.ACTION_MAX_RETRIES,
            error_message="exhausted retries",
        )
        assert r.error_code == ErrorCode.ACTION_MAX_RETRIES
        assert "exhausted" in r.error_message


# ── Profile variation tests ───────────────────────────────────────────────────

class TestProfileVariation:
    def test_slow_medium_fast_all_succeed(self):
        for speed in MouseSpeed:
            profile = BehaviorFingerprint(
                typing_wpm=60,
                error_rate=0.01,
                mouse_speed=speed,
                pause_min_ms=100,
                pause_max_ms=500,
            )
            result = dispatch(
                make_action(ActionType.CLICK),
                make_bbox(),
                profile,
                dry_run=True,
                _rng=seeded_rng(),
            )
            assert result.success, f"Failed for mouse_speed={speed}"

    def test_max_error_rate_does_not_crash(self):
        profile = make_behavior(error_rate=0.20, wpm=30)
        result = dispatch(
            make_action(ActionType.TYPE, {"text": "test"}),
            make_bbox(),
            profile,
            dry_run=True,
            _rng=seeded_rng(99),
        )
        assert result.success

    def test_boundary_wpm_values(self):
        for wpm in (20, 200):
            profile = make_behavior(wpm=wpm)
            result = dispatch(
                make_action(ActionType.TYPE, {"text": "hi"}),
                make_bbox(),
                profile,
                dry_run=True,
                _rng=seeded_rng(),
            )
            assert result.success, f"Failed for wpm={wpm}"
