# test_phase7_8.py — Phase 7–8: FSM + Orchestrator
# SCHEMA_VERSION: 1
#
# Phase 7 tests: FSM transition validation, history, listeners, checkpoint/restore.
# Phase 8 tests: orchestrator state handlers (mocked capture/perception/actions).

from __future__ import annotations

import time
import unittest.mock as mock

import numpy as np
import pytest

from careerbridge.errors import ErrorCode, SchemaError, StateError
from careerbridge.fsm import AssessmentFSM, FSMTransition, FSM_VERSION
from careerbridge.orchestrator import AssessmentOrchestrator, _build_ui_state
from careerbridge.schema import (
    BehaviorFingerprint,
    BigFive,
    BoundingBox,
    LinguisticTraits,
    Profile,
    ResponseBias,
    UIElement,
    UIState,
)
from careerbridge.types import ChangeType, ElementType, FSMState, MouseSpeed, PerceptionSource


# ── Fixtures ──────────────────────────────────────────────────────────────────

def _profile(profile_id: str = "test-001") -> Profile:
    return Profile(
        profile_id=profile_id,
        name="Test User",
        big_five=BigFive(50, 60, 40, 70, 30),
        response_bias=ResponseBias(0.3, 0.2, 0.5, 0.8),
        linguistic_traits=LinguisticTraits(0.5, 0.6, 0.7),
        behavior=BehaviorFingerprint(
            typing_wpm=80,
            error_rate=0.02,
            mouse_speed=MouseSpeed.MEDIUM,
            pause_min_ms=100,
            pause_max_ms=500,
        ),
        created_at="2026-01-01T00:00:00Z",
        runs=0,
    )


def _make_frame(frame_id: int = 0, fill: int = 0):
    from careerbridge.capture import CaptureBackend, CaptureFrame
    h, w = 100, 200
    data = np.full((h, w, 4), fill, dtype=np.uint8)
    bbox = BoundingBox(x=0, y=0, w=w, h=h)
    return CaptureFrame(
        frame_id=frame_id,
        timestamp=time.monotonic(),
        data=data,
        window_title="TestWin",
        window_bbox=bbox,
        region=None,
        backend=CaptureBackend.MSS,
    )


# ══════════════════════════════════════════════════════════════════════════════
# FSMTransition validation
# ══════════════════════════════════════════════════════════════════════════════

class TestFSMTransition:
    def test_valid_transition_constructs(self):
        t = FSMTransition(FSMState.INIT, FSMState.NAVIGATE, time.monotonic(), "start")
        assert t.from_state == FSMState.INIT
        assert t.to_state == FSMState.NAVIGATE

    def test_zero_timestamp_rejected(self):
        with pytest.raises(ValueError, match="timestamp must be > 0"):
            FSMTransition(FSMState.INIT, FSMState.NAVIGATE, 0.0, "x")

    def test_negative_timestamp_rejected(self):
        with pytest.raises(ValueError, match="timestamp must be > 0"):
            FSMTransition(FSMState.INIT, FSMState.NAVIGATE, -1.0, "x")


# ══════════════════════════════════════════════════════════════════════════════
# AssessmentFSM — construction
# ══════════════════════════════════════════════════════════════════════════════

class TestFSMConstruction:
    def test_starts_in_init(self):
        fsm = AssessmentFSM("p1")
        assert fsm.state == FSMState.INIT

    def test_empty_profile_id_rejected(self):
        with pytest.raises(ValueError):
            AssessmentFSM("")

    def test_repr_contains_state(self):
        fsm = AssessmentFSM("p1")
        assert "init" in repr(fsm)

    def test_history_empty_at_start(self):
        fsm = AssessmentFSM("p1")
        assert fsm.history == ()

    def test_profile_id_stored(self):
        fsm = AssessmentFSM("my-profile")
        assert fsm.profile_id == "my-profile"


# ══════════════════════════════════════════════════════════════════════════════
# Transitions
# ══════════════════════════════════════════════════════════════════════════════

class TestFSMTransitions:
    def test_valid_transition_changes_state(self):
        fsm = AssessmentFSM("p1")
        fsm.transition(FSMState.NAVIGATE, "test")
        assert fsm.state == FSMState.NAVIGATE

    def test_invalid_transition_raises_state_error(self):
        fsm = AssessmentFSM("p1")  # in INIT
        with pytest.raises(StateError) as exc:
            fsm.transition(FSMState.COMPLETE)  # INIT → COMPLETE invalid
        assert exc.value.code == ErrorCode.STATE_INVALID_TRANSITION

    def test_full_happy_path(self):
        fsm = AssessmentFSM("p1")
        path = [
            FSMState.NAVIGATE,
            FSMState.WAIT_UI,
            FSMState.EXTRACT,
            FSMState.REASON,
            FSMState.EXECUTE,
            FSMState.VERIFY,
            FSMState.COMPLETE,
        ]
        for s in path:
            fsm.transition(s, "ok")
        assert fsm.state == FSMState.COMPLETE

    def test_error_transition_from_any_execution_state(self):
        for start in [FSMState.NAVIGATE, FSMState.WAIT_UI, FSMState.EXTRACT,
                      FSMState.REASON, FSMState.EXECUTE, FSMState.VERIFY]:
            fsm = AssessmentFSM("p1")
            # Bring FSM to start state via valid path
            _drive_to(fsm, start)
            fsm.transition(FSMState.ERROR, "deliberate error")
            assert fsm.state == FSMState.ERROR

    def test_to_error_convenience(self):
        fsm = AssessmentFSM("p1")
        fsm.transition(FSMState.NAVIGATE, "start")
        fsm.to_error("something broke")
        assert fsm.state == FSMState.ERROR

    def test_to_error_noop_when_already_error(self):
        fsm = AssessmentFSM("p1")
        fsm.transition(FSMState.ERROR, "first error")
        fsm.to_error("second error")  # must not raise
        assert fsm.state == FSMState.ERROR
        assert len(fsm.history) == 1  # only one transition recorded

    def test_recovery_from_error(self):
        fsm = AssessmentFSM("p1")
        fsm.transition(FSMState.ERROR, "err")
        fsm.recover()
        assert fsm.state == FSMState.NAVIGATE

    def test_recover_from_non_error_raises(self):
        fsm = AssessmentFSM("p1")
        with pytest.raises(StateError):
            fsm.recover()

    def test_is_terminal_complete(self):
        fsm = AssessmentFSM("p1")
        _drive_to(fsm, FSMState.COMPLETE)
        assert fsm.is_terminal() is True

    def test_is_terminal_error(self):
        fsm = AssessmentFSM("p1")
        fsm.transition(FSMState.ERROR, "err")
        assert fsm.is_terminal() is True

    def test_is_terminal_false_mid_run(self):
        fsm = AssessmentFSM("p1")
        fsm.transition(FSMState.NAVIGATE, "go")
        assert fsm.is_terminal() is False

    def test_can_transition_to_valid(self):
        fsm = AssessmentFSM("p1")
        assert fsm.can_transition_to(FSMState.NAVIGATE) is True

    def test_can_transition_to_invalid(self):
        fsm = AssessmentFSM("p1")
        assert fsm.can_transition_to(FSMState.COMPLETE) is False

    def test_verify_back_to_execute(self):
        """VERIFY → EXECUTE is valid (more actions pending)."""
        fsm = AssessmentFSM("p1")
        _drive_to(fsm, FSMState.VERIFY)
        fsm.transition(FSMState.EXECUTE, "more actions")
        assert fsm.state == FSMState.EXECUTE


# ══════════════════════════════════════════════════════════════════════════════
# History
# ══════════════════════════════════════════════════════════════════════════════

class TestFSMHistory:
    def test_transition_recorded_in_history(self):
        fsm = AssessmentFSM("p1")
        fsm.transition(FSMState.NAVIGATE, "start")
        assert len(fsm.history) == 1
        assert fsm.history[0].from_state == FSMState.INIT
        assert fsm.history[0].to_state == FSMState.NAVIGATE
        assert fsm.history[0].reason == "start"

    def test_history_is_tuple(self):
        fsm = AssessmentFSM("p1")
        assert isinstance(fsm.history, tuple)

    def test_history_immutable(self):
        fsm = AssessmentFSM("p1")
        fsm.transition(FSMState.NAVIGATE, "a")
        h = fsm.history
        with pytest.raises((AttributeError, TypeError)):
            h[0] = None  # type: ignore

    def test_multiple_transitions_all_recorded(self):
        fsm = AssessmentFSM("p1")
        fsm.transition(FSMState.NAVIGATE, "a")
        fsm.transition(FSMState.WAIT_UI, "b")
        assert len(fsm.history) == 2

    def test_timestamps_monotonic(self):
        fsm = AssessmentFSM("p1")
        fsm.transition(FSMState.NAVIGATE, "a")
        fsm.transition(FSMState.WAIT_UI, "b")
        assert fsm.history[1].timestamp >= fsm.history[0].timestamp


# ══════════════════════════════════════════════════════════════════════════════
# Context
# ══════════════════════════════════════════════════════════════════════════════

class TestFSMContext:
    def test_set_and_get_context(self):
        fsm = AssessmentFSM("p1")
        fsm.set_context("foo", 42)
        assert fsm.get_context("foo") == 42

    def test_get_missing_key_returns_default(self):
        fsm = AssessmentFSM("p1")
        assert fsm.get_context("missing", "default") == "default"

    def test_get_missing_key_returns_none_by_default(self):
        fsm = AssessmentFSM("p1")
        assert fsm.get_context("missing") is None

    def test_context_survives_transition(self):
        fsm = AssessmentFSM("p1")
        fsm.set_context("key", "value")
        fsm.transition(FSMState.NAVIGATE, "go")
        assert fsm.get_context("key") == "value"

    def test_clear_context(self):
        fsm = AssessmentFSM("p1")
        fsm.set_context("x", 1)
        fsm.clear_context("x")
        assert fsm.get_context("x") is None

    def test_clear_nonexistent_key_no_error(self):
        fsm = AssessmentFSM("p1")
        fsm.clear_context("nonexistent")  # must not raise


# ══════════════════════════════════════════════════════════════════════════════
# Listeners
# ══════════════════════════════════════════════════════════════════════════════

class TestFSMListeners:
    def test_listener_called_on_transition(self):
        fsm = AssessmentFSM("p1")
        received = []
        fsm.add_listener(received.append)
        fsm.transition(FSMState.NAVIGATE, "go")
        assert len(received) == 1
        assert received[0].to_state == FSMState.NAVIGATE

    def test_multiple_listeners(self):
        fsm = AssessmentFSM("p1")
        a, b = [], []
        fsm.add_listener(a.append)
        fsm.add_listener(b.append)
        fsm.transition(FSMState.NAVIGATE, "go")
        assert len(a) == 1 and len(b) == 1

    def test_crashing_listener_does_not_abort_transition(self):
        fsm = AssessmentFSM("p1")
        fsm.add_listener(lambda t: 1 / 0)  # always raises
        fsm.transition(FSMState.NAVIGATE, "go")  # must not raise
        assert fsm.state == FSMState.NAVIGATE

    def test_remove_listener(self):
        fsm = AssessmentFSM("p1")
        received = []
        fn = received.append
        fsm.add_listener(fn)
        fsm.remove_listener(fn)
        fsm.transition(FSMState.NAVIGATE, "go")
        assert received == []


# ══════════════════════════════════════════════════════════════════════════════
# Checkpoint / restore
# ══════════════════════════════════════════════════════════════════════════════

class TestFSMCheckpoint:
    def test_checkpoint_contains_version(self):
        fsm = AssessmentFSM("p1")
        data = fsm.checkpoint()
        assert data["version"] == FSM_VERSION

    def test_checkpoint_contains_state(self):
        fsm = AssessmentFSM("p1")
        fsm.transition(FSMState.NAVIGATE, "go")
        data = fsm.checkpoint()
        assert data["state"] == "navigate"

    def test_checkpoint_contains_history(self):
        fsm = AssessmentFSM("p1")
        fsm.transition(FSMState.NAVIGATE, "reason")
        data = fsm.checkpoint()
        assert len(data["history"]) == 1
        assert data["history"][0]["reason"] == "reason"

    def test_checkpoint_json_serializable(self):
        import json
        fsm = AssessmentFSM("p1")
        fsm.set_context("count", 42)
        fsm.transition(FSMState.NAVIGATE, "go")
        json.dumps(fsm.checkpoint())  # must not raise

    def test_checkpoint_skips_non_json_context(self):
        fsm = AssessmentFSM("p1")
        fsm.set_context("good", "value")
        fsm.set_context("bad", object())  # not JSON serializable
        data = fsm.checkpoint()
        assert "good" in data["context"]
        assert "bad" not in data["context"]

    def test_restore_state(self):
        fsm = AssessmentFSM("p1")
        fsm.transition(FSMState.NAVIGATE, "go")
        data = fsm.checkpoint()
        restored = AssessmentFSM.from_checkpoint(data)
        assert restored.state == FSMState.NAVIGATE

    def test_restore_profile_id(self):
        fsm = AssessmentFSM("my-id")
        data = fsm.checkpoint()
        restored = AssessmentFSM.from_checkpoint(data)
        assert restored.profile_id == "my-id"

    def test_restore_history(self):
        fsm = AssessmentFSM("p1")
        fsm.transition(FSMState.NAVIGATE, "step1")
        fsm.transition(FSMState.WAIT_UI, "step2")
        data = fsm.checkpoint()
        restored = AssessmentFSM.from_checkpoint(data)
        assert len(restored.history) == 2
        assert restored.history[0].reason == "step1"

    def test_restore_context(self):
        fsm = AssessmentFSM("p1")
        fsm.set_context("x", 99)
        data = fsm.checkpoint()
        restored = AssessmentFSM.from_checkpoint(data)
        assert restored.get_context("x") == 99

    def test_restore_listeners_empty(self):
        """Listeners are NOT restored from checkpoint."""
        fsm = AssessmentFSM("p1")
        received = []
        fsm.add_listener(received.append)
        data = fsm.checkpoint()
        restored = AssessmentFSM.from_checkpoint(data)
        restored.transition(FSMState.NAVIGATE, "go")
        assert received == []  # old listener not fired

    def test_wrong_version_raises_schema_error(self):
        fsm = AssessmentFSM("p1")
        data = fsm.checkpoint()
        data["version"] = 999
        with pytest.raises(SchemaError) as exc:
            AssessmentFSM.from_checkpoint(data)
        assert exc.value.code == ErrorCode.SCHEMA_VERSION_MISMATCH

    def test_round_trip_full_run(self):
        fsm = AssessmentFSM("p1")
        _drive_to(fsm, FSMState.VERIFY)
        data = fsm.checkpoint()
        restored = AssessmentFSM.from_checkpoint(data)
        assert restored.state == FSMState.VERIFY
        assert len(restored.history) == len(fsm.history)


# ══════════════════════════════════════════════════════════════════════════════
# _build_ui_state
# ══════════════════════════════════════════════════════════════════════════════

class TestBuildUiState:
    def test_merges_uia_and_ocr(self):
        frame = _make_frame()
        uia = [UIElement(ElementType.BUTTON, "OK",
                         BoundingBox(0, 0, 50, 20), 0.9,
                         PerceptionSource.UIA, 0)]
        ocr = [UIElement(ElementType.TEXT, "Question?",
                         BoundingBox(0, 30, 200, 20), 0.85,
                         PerceptionSource.OCR, 0)]
        state = _build_ui_state(frame, uia, ocr)
        assert len(state.elements) == 2

    def test_empty_elements_ok(self):
        frame = _make_frame()
        state = _build_ui_state(frame, [], [])
        assert len(state.elements) == 0

    def test_frame_metadata_copied(self):
        frame = _make_frame(frame_id=7)
        state = _build_ui_state(frame, [], [])
        assert state.frame_id == 7
        assert state.window_title == "TestWin"


# ══════════════════════════════════════════════════════════════════════════════
# AssessmentOrchestrator — unit tests (mocked layers)
# ══════════════════════════════════════════════════════════════════════════════

class TestOrchestratorNoSOP:
    """Orchestrator with no SOP/navigator: goes straight NAVIGATE→WAIT_UI→..."""

    def _make_orch(self, reasoner=None, dry_run=True, **kwargs):
        return AssessmentOrchestrator(
            window_title="TestWin",
            profile=_profile(),
            reasoner=reasoner,
            dry_run=dry_run,
            **kwargs,
        )

    def test_starts_in_init(self):
        orch = self._make_orch()
        assert orch.fsm.state == FSMState.INIT

    def test_no_reasoner_run_reaches_complete(self):
        """Without a reasoner the loop should reach COMPLETE after REASON."""
        frame0 = _make_frame(0, fill=0)
        frame1 = _make_frame(1, fill=0)  # identical → NONE diff → UI settled

        mock_session = mock.MagicMock()
        mock_session.__enter__ = mock.Mock(return_value=mock_session)
        mock_session.__exit__ = mock.Mock(return_value=False)
        mock_session.grab.side_effect = [frame0, frame1, frame1]

        orch = self._make_orch(poll_interval_s=0.0, wait_ui_timeout_s=5.0)

        with mock.patch("careerbridge.orchestrator.CaptureSession",
                        return_value=mock_session), \
             mock.patch("careerbridge.orchestrator.extract_uia_elements",
                        return_value=[]), \
             mock.patch("careerbridge.orchestrator.extract_ocr_elements",
                        return_value=[]):
            final = orch.run()

        assert final == FSMState.COMPLETE

    def test_capture_failure_goes_to_error(self):
        from careerbridge.errors import CaptureError
        mock_session = mock.MagicMock()
        mock_session.__enter__ = mock.Mock(return_value=mock_session)
        mock_session.__exit__ = mock.Mock(return_value=False)
        mock_session.grab.side_effect = CaptureError(
            ErrorCode.CAPTURE_WINDOW_NOT_FOUND, "window gone"
        )

        orch = self._make_orch(poll_interval_s=0.0, wait_ui_timeout_s=1.0)

        with mock.patch("careerbridge.orchestrator.CaptureSession",
                        return_value=mock_session):
            final = orch.run()

        assert final == FSMState.ERROR

    def test_loop_timeout_goes_to_error(self):
        """A session that never settles should time out."""
        mock_session = mock.MagicMock()
        mock_session.__enter__ = mock.Mock(return_value=mock_session)
        mock_session.__exit__ = mock.Mock(return_value=False)
        # Alternate frames so diff is always CONTENT — never settles
        mock_session.grab.side_effect = [
            _make_frame(i, fill=i % 2 * 200) for i in range(200)
        ]

        orch = self._make_orch(
            poll_interval_s=0.0,
            wait_ui_timeout_s=0.01,
            loop_timeout_s=0.05,
        )

        with mock.patch("careerbridge.orchestrator.CaptureSession",
                        return_value=mock_session), \
             mock.patch("careerbridge.orchestrator.extract_uia_elements",
                        return_value=[]), \
             mock.patch("careerbridge.orchestrator.extract_ocr_elements",
                        return_value=[]):
            final = orch.run()

        assert final == FSMState.ERROR

    def test_fsm_history_records_transitions(self):
        frame0 = _make_frame(0, fill=0)
        frame1 = _make_frame(1, fill=0)

        mock_session = mock.MagicMock()
        mock_session.__enter__ = mock.Mock(return_value=mock_session)
        mock_session.__exit__ = mock.Mock(return_value=False)
        mock_session.grab.side_effect = [frame0, frame1, frame1]

        orch = self._make_orch(poll_interval_s=0.0, wait_ui_timeout_s=5.0)

        with mock.patch("careerbridge.orchestrator.CaptureSession",
                        return_value=mock_session), \
             mock.patch("careerbridge.orchestrator.extract_uia_elements",
                        return_value=[]), \
             mock.patch("careerbridge.orchestrator.extract_ocr_elements",
                        return_value=[]):
            orch.run()

        states_visited = [t.to_state for t in orch.fsm.history]
        assert FSMState.NAVIGATE in states_visited
        assert FSMState.WAIT_UI in states_visited
        assert FSMState.EXTRACT in states_visited
        assert FSMState.REASON in states_visited
        assert FSMState.COMPLETE in states_visited

    def test_checkpoint_mid_run(self):
        """FSM checkpoint is valid JSON at any point."""
        import json
        fsm = AssessmentFSM("p1")
        _drive_to(fsm, FSMState.EXTRACT)
        data = fsm.checkpoint()
        json.dumps(data)  # must not raise

    def test_reasoner_exception_goes_to_error(self):
        frame0 = _make_frame(0, fill=0)
        frame1 = _make_frame(1, fill=0)

        def bad_reasoner(ui_state, profile):
            raise RuntimeError("LLM exploded")

        mock_session = mock.MagicMock()
        mock_session.__enter__ = mock.Mock(return_value=mock_session)
        mock_session.__exit__ = mock.Mock(return_value=False)
        mock_session.grab.side_effect = [frame0, frame1, frame1]

        orch = self._make_orch(
            reasoner=bad_reasoner,
            poll_interval_s=0.0,
            wait_ui_timeout_s=5.0,
        )

        with mock.patch("careerbridge.orchestrator.CaptureSession",
                        return_value=mock_session), \
             mock.patch("careerbridge.orchestrator.extract_uia_elements",
                        return_value=[]), \
             mock.patch("careerbridge.orchestrator.extract_ocr_elements",
                        return_value=[]):
            final = orch.run()

        assert final == FSMState.ERROR


# ══════════════════════════════════════════════════════════════════════════════
# Helpers
# ══════════════════════════════════════════════════════════════════════════════

def _drive_to(fsm: AssessmentFSM, target: FSMState) -> None:
    """Drive the FSM to a target state via the standard happy path."""
    path = {
        FSMState.NAVIGATE: [FSMState.NAVIGATE],
        FSMState.WAIT_UI:  [FSMState.NAVIGATE, FSMState.WAIT_UI],
        FSMState.EXTRACT:  [FSMState.NAVIGATE, FSMState.WAIT_UI, FSMState.EXTRACT],
        FSMState.REASON:   [FSMState.NAVIGATE, FSMState.WAIT_UI, FSMState.EXTRACT, FSMState.REASON],
        FSMState.EXECUTE:  [FSMState.NAVIGATE, FSMState.WAIT_UI, FSMState.EXTRACT, FSMState.REASON, FSMState.EXECUTE],
        FSMState.VERIFY:   [FSMState.NAVIGATE, FSMState.WAIT_UI, FSMState.EXTRACT, FSMState.REASON, FSMState.EXECUTE, FSMState.VERIFY],
        FSMState.COMPLETE: [FSMState.NAVIGATE, FSMState.WAIT_UI, FSMState.EXTRACT, FSMState.REASON, FSMState.EXECUTE, FSMState.VERIFY, FSMState.COMPLETE],
        FSMState.ERROR:    [FSMState.ERROR],
    }
    for s in path[target]:
        fsm.transition(s, "driven")
