# test_phase0.py — Phase 0 contract tests
# Tests ONLY: schema validation, invalid schema rejection, state transitions, events, errors.
# No IO, no network, no external dependencies beyond standard library.
# Every test must be deterministic and pass on every run.

import sys
import os
import pytest

# Allow running from anywhere inside cb-core/
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

from careerbridge.types import (
    ActionType, ElementType, FSMState, MouseSpeed, PerceptionSource,
)
from careerbridge.errors import (
    ActionError, CareerBridgeError, CaptureError, ErrorCode,
    LLMError, PerceptionError, PersistenceError, ProfileError,
    SchemaError, SOPError, StateError,
)
from careerbridge.schema import (
    SCHEMA_VERSION,
    Action, BehaviorFingerprint, BigFive, BoundingBox,
    LinguisticTraits, Profile, ResponseBias, SOP, SOPStep,
    UIElement, UIState, _element_hash, _state_hash,
)
from careerbridge.events import (
    Event, EventType,
    SOURCE_ACTION, SOURCE_CAPTURE, SOURCE_FSM,
    SOURCE_PERCEPTION, SOURCE_PERSISTENCE, SOURCE_REASONING, SOURCE_SYSTEM,
)
from careerbridge.states import (
    EXECUTION_STATES, PERCEPTION_STATES, REASONING_STATES,
    TERMINAL_STATES, VALID_TRANSITIONS,
    assert_valid_transition, is_valid_transition, reachable_from,
)


# ── Fixtures ──────────────────────────────────────────────────────────────────

def make_bbox(x=10, y=20, w=100, h=30) -> BoundingBox:
    return BoundingBox(x=x, y=y, w=w, h=h)


def make_element(
    text="Strongly Agree",
    bbox=None,
    element_type=ElementType.RADIO,
    source=PerceptionSource.OCR,
    confidence=0.92,
    frame_id=1,
) -> UIElement:
    return UIElement(
        element_type=element_type,
        text=text,
        bbox=bbox or make_bbox(),
        confidence=confidence,
        source=source,
        frame_id=frame_id,
    )


def make_behavior() -> BehaviorFingerprint:
    return BehaviorFingerprint(
        typing_wpm=62,
        error_rate=0.03,
        mouse_speed=MouseSpeed.MEDIUM,
        pause_min_ms=200,
        pause_max_ms=900,
    )


def make_profile(name="john", profile_id="prof_001") -> Profile:
    return Profile(
        profile_id=profile_id,
        name=name,
        big_five=BigFive(72, 65, 45, 70, 30),
        response_bias=ResponseBias(0.18, 0.31, 0.52, 0.81),
        linguistic_traits=LinguisticTraits(0.42, 0.68, 0.57),
        behavior=make_behavior(),
        created_at="2026-05-18T00:00:00Z",
        runs=0,
    )


def make_sop_step(index=0) -> SOPStep:
    return SOPStep(
        step_index=index,
        action_type=ActionType.CLICK,
        anchor_text="Start Assessment",
        wait_for="question_block",
        payload={},
    )


def make_sop() -> SOP:
    return SOP(
        sop_id="abc123def456abc1",
        site_url="https://example.com/assessment",
        steps=(make_sop_step(0), make_sop_step(1)),
        recorded_at="2026-05-18T00:00:00Z",
        last_verified="2026-05-18T00:00:00Z",
        success_rate=1.0,
    )


def make_action(action_type=ActionType.CLICK, payload=None) -> Action:
    return Action(
        action_id="act_001",
        action_type=action_type,
        target_element_id="elem_abc",
        payload=payload or {},
        profile_id="prof_001",
        frame_id=1,
    )


# ── BoundingBox tests ─────────────────────────────────────────────────────────

class TestBoundingBox:
    def test_valid(self):
        bb = make_bbox()
        assert bb.x == 10 and bb.y == 20 and bb.w == 100 and bb.h == 30

    def test_center(self):
        bb = BoundingBox(x=0, y=0, w=100, h=50)
        assert bb.center_x == 50
        assert bb.center_y == 25

    def test_negative_origin_allowed(self):
        # multi-monitor: windows can have negative screen coords
        bb = BoundingBox(x=-100, y=-50, w=200, h=100)
        assert bb.x == -100

    def test_zero_width_rejected(self):
        with pytest.raises(ValueError, match="w must be > 0"):
            BoundingBox(x=0, y=0, w=0, h=10)

    def test_negative_width_rejected(self):
        with pytest.raises(ValueError, match="w must be > 0"):
            BoundingBox(x=0, y=0, w=-5, h=10)

    def test_zero_height_rejected(self):
        with pytest.raises(ValueError, match="h must be > 0"):
            BoundingBox(x=0, y=0, w=10, h=0)

    def test_immutable(self):
        bb = make_bbox()
        with pytest.raises((AttributeError, TypeError)):
            bb.x = 999  # type: ignore


# ── BigFive tests ─────────────────────────────────────────────────────────────

class TestBigFive:
    def test_valid_boundaries(self):
        bf = BigFive(0, 100, 50, 0, 100)
        assert bf.openness == 0

    def test_all_100(self):
        BigFive(100, 100, 100, 100, 100)

    def test_above_100_rejected(self):
        with pytest.raises(ValueError, match="openness must be 0–100"):
            BigFive(101, 50, 50, 50, 50)

    def test_negative_rejected(self):
        with pytest.raises(ValueError, match="neuroticism must be 0–100"):
            BigFive(50, 50, 50, 50, -1)


# ── ResponseBias tests ────────────────────────────────────────────────────────

class TestResponseBias:
    def test_valid(self):
        rb = ResponseBias(0.18, 0.31, 0.52, 0.81)
        assert rb.consistency_strength == 0.81

    def test_out_of_range_rejected(self):
        with pytest.raises(ValueError, match="extreme_answer_rate must be 0.0–1.0"):
            ResponseBias(1.01, 0.3, 0.5, 0.8)

    def test_negative_rejected(self):
        with pytest.raises(ValueError, match="neutral_preference must be 0.0–1.0"):
            ResponseBias(0.2, -0.1, 0.5, 0.8)


# ── BehaviorFingerprint tests ─────────────────────────────────────────────────

class TestBehaviorFingerprint:
    def test_valid(self):
        b = make_behavior()
        assert b.typing_wpm == 62

    def test_wpm_too_low(self):
        with pytest.raises(ValueError, match="typing_wpm must be 20–200"):
            BehaviorFingerprint(19, 0.01, MouseSpeed.MEDIUM, 100, 500)

    def test_wpm_too_high(self):
        with pytest.raises(ValueError, match="typing_wpm must be 20–200"):
            BehaviorFingerprint(201, 0.01, MouseSpeed.MEDIUM, 100, 500)

    def test_error_rate_too_high(self):
        with pytest.raises(ValueError, match="error_rate must be 0.0–0.20"):
            BehaviorFingerprint(60, 0.21, MouseSpeed.MEDIUM, 100, 500)

    def test_pause_inverted(self):
        with pytest.raises(ValueError, match="pause_max_ms.*must be > pause_min_ms"):
            BehaviorFingerprint(60, 0.02, MouseSpeed.SLOW, 500, 100)

    def test_pause_equal_rejected(self):
        with pytest.raises(ValueError, match="pause_max_ms.*must be > pause_min_ms"):
            BehaviorFingerprint(60, 0.02, MouseSpeed.SLOW, 500, 500)


# ── UIElement tests ───────────────────────────────────────────────────────────

class TestUIElement:
    def test_valid_construction(self):
        e = make_element()
        assert e.text == "Strongly Agree"
        assert e.element_type == ElementType.RADIO
        assert e.schema_version == SCHEMA_VERSION

    def test_element_id_computed(self):
        e = make_element()
        expected = _element_hash(e.text, e.bbox, e.source)
        assert e.element_id == expected

    def test_element_id_deterministic(self):
        e1 = make_element()
        e2 = make_element()
        assert e1.element_id == e2.element_id

    def test_different_text_different_id(self):
        e1 = make_element(text="Agree")
        e2 = make_element(text="Disagree")
        assert e1.element_id != e2.element_id

    def test_different_source_different_id(self):
        e1 = make_element(source=PerceptionSource.UIA)
        e2 = make_element(source=PerceptionSource.OCR)
        assert e1.element_id != e2.element_id

    def test_confidence_above_1_rejected(self):
        with pytest.raises(ValueError, match="confidence must be 0.0–1.0"):
            make_element(confidence=1.01)

    def test_negative_confidence_rejected(self):
        with pytest.raises(ValueError, match="confidence must be 0.0–1.0"):
            make_element(confidence=-0.1)

    def test_negative_frame_id_rejected(self):
        with pytest.raises(ValueError, match="frame_id must be >= 0"):
            make_element(frame_id=-1)

    def test_immutable(self):
        e = make_element()
        with pytest.raises((AttributeError, TypeError)):
            e.text = "changed"  # type: ignore

    def test_schema_version_correct(self):
        e = make_element()
        assert e.schema_version == SCHEMA_VERSION


# ── UIState tests ─────────────────────────────────────────────────────────────

class TestUIState:
    def _make_state(self, elements=None):
        elems = elements if elements is not None else (make_element(),)
        return UIState(
            frame_id=1,
            timestamp=1.0,
            window_title="IXBrowser - Profile 3",
            window_bbox=make_bbox(0, 0, 1280, 800),
            elements=elems,
        )

    def test_valid(self):
        s = self._make_state()
        assert s.frame_id == 1
        assert s.schema_version == SCHEMA_VERSION

    def test_state_hash_computed(self):
        s = self._make_state()
        expected = _state_hash(s.frame_id, s.elements)
        assert s.state_hash == expected

    def test_empty_elements_allowed(self):
        s = self._make_state(elements=())
        assert s.elements == ()

    def test_list_elements_rejected(self):
        with pytest.raises(TypeError, match="must be a tuple"):
            UIState(
                frame_id=1,
                timestamp=1.0,
                window_title="test",
                window_bbox=make_bbox(),
                elements=[make_element()],  # type: ignore
            )

    def test_empty_title_rejected(self):
        with pytest.raises(ValueError, match="window_title must not be empty"):
            UIState(frame_id=1, timestamp=1.0, window_title="",
                    window_bbox=make_bbox(), elements=())

    def test_zero_timestamp_rejected(self):
        with pytest.raises(ValueError, match="timestamp must be > 0"):
            UIState(frame_id=1, timestamp=0, window_title="t",
                    window_bbox=make_bbox(), elements=())

    def test_negative_frame_rejected(self):
        with pytest.raises(ValueError, match="frame_id must be >= 0"):
            UIState(frame_id=-1, timestamp=1.0, window_title="t",
                    window_bbox=make_bbox(), elements=())

    def test_different_elements_different_hash(self):
        e1 = make_element(text="Agree")
        e2 = make_element(text="Disagree")
        s1 = self._make_state(elements=(e1,))
        s2 = self._make_state(elements=(e2,))
        assert s1.state_hash != s2.state_hash


# ── Action tests ──────────────────────────────────────────────────────────────

class TestAction:
    def test_valid_click(self):
        a = make_action(ActionType.CLICK, {})
        assert a.action_type == ActionType.CLICK

    def test_valid_type(self):
        a = make_action(ActionType.TYPE, {"text": "hello"})
        assert a.payload["text"] == "hello"

    def test_valid_scroll_down(self):
        a = make_action(ActionType.SCROLL, {"direction": "down", "amount": 3})
        assert a.payload["direction"] == "down"

    def test_valid_scroll_up(self):
        make_action(ActionType.SCROLL, {"direction": "up", "amount": 1})

    def test_payload_is_frozen(self):
        a = make_action(ActionType.CLICK, {})
        with pytest.raises(TypeError):
            a.payload["injected"] = "evil"  # type: ignore

    def test_type_missing_text_rejected(self):
        with pytest.raises(ValueError, match="TYPE payload must contain 'text'"):
            make_action(ActionType.TYPE, {})

    def test_type_non_string_text_rejected(self):
        with pytest.raises(ValueError, match="TYPE payload must contain 'text'"):
            make_action(ActionType.TYPE, {"text": 123})

    def test_scroll_bad_direction_rejected(self):
        with pytest.raises(ValueError, match="direction must be 'up' or 'down'"):
            make_action(ActionType.SCROLL, {"direction": "left", "amount": 3})

    def test_scroll_zero_amount_rejected(self):
        with pytest.raises(ValueError, match="amount must be int > 0"):
            make_action(ActionType.SCROLL, {"direction": "down", "amount": 0})

    def test_scroll_float_amount_rejected(self):
        with pytest.raises(ValueError, match="amount must be int > 0"):
            make_action(ActionType.SCROLL, {"direction": "down", "amount": 1.5})

    def test_empty_action_id_rejected(self):
        with pytest.raises(ValueError, match="action_id must not be empty"):
            Action("", ActionType.CLICK, "elem", {}, "prof", 1)

    def test_empty_profile_id_rejected(self):
        with pytest.raises(ValueError, match="profile_id must not be empty"):
            Action("act_1", ActionType.CLICK, "elem", {}, "", 1)

    def test_schema_version_set(self):
        a = make_action()
        assert a.schema_version == SCHEMA_VERSION


# ── SOPStep tests ─────────────────────────────────────────────────────────────

class TestSOPStep:
    def test_valid(self):
        s = make_sop_step(0)
        assert s.step_index == 0
        assert s.anchor_text == "Start Assessment"

    def test_negative_index_rejected(self):
        with pytest.raises(ValueError, match="step_index must be >= 0"):
            SOPStep(-1, ActionType.CLICK, "anchor", "wait", {})

    def test_empty_anchor_rejected(self):
        with pytest.raises(ValueError, match="anchor_text must not be empty"):
            SOPStep(0, ActionType.CLICK, "", "wait", {})

    def test_empty_wait_for_rejected(self):
        with pytest.raises(ValueError, match="wait_for must not be empty"):
            SOPStep(0, ActionType.CLICK, "anchor", "", {})

    def test_payload_frozen(self):
        s = make_sop_step()
        with pytest.raises(TypeError):
            s.payload["injected"] = "evil"  # type: ignore


# ── SOP tests ─────────────────────────────────────────────────────────────────

class TestSOP:
    def test_valid(self):
        sop = make_sop()
        assert len(sop.steps) == 2
        assert sop.schema_version == SCHEMA_VERSION

    def test_empty_steps_rejected(self):
        with pytest.raises(ValueError, match="steps must not be empty"):
            SOP("id", "https://x.com", (), "2026-01-01", "2026-01-01", 1.0)

    def test_list_steps_rejected(self):
        with pytest.raises(TypeError, match="must be a tuple"):
            SOP("id", "https://x.com", [make_sop_step()],  # type: ignore
                "2026-01-01", "2026-01-01", 1.0)

    def test_non_contiguous_indices_rejected(self):
        s0 = make_sop_step(0)
        s2 = make_sop_step(2)  # skips index 1
        with pytest.raises(ValueError, match="contiguous 0-based indices"):
            SOP("id", "https://x.com", (s0, s2), "2026-01-01", "2026-01-01", 1.0)

    def test_success_rate_above_1_rejected(self):
        with pytest.raises(ValueError, match="success_rate must be 0.0–1.0"):
            SOP("id", "https://x.com", (make_sop_step(0),),
                "2026-01-01", "2026-01-01", 1.01)

    def test_empty_url_rejected(self):
        with pytest.raises(ValueError, match="site_url must not be empty"):
            SOP("id", "", (make_sop_step(0),), "2026-01-01", "2026-01-01", 1.0)


# ── Profile tests ─────────────────────────────────────────────────────────────

class TestProfile:
    def test_valid(self):
        p = make_profile()
        assert p.name == "john"
        assert p.schema_version == SCHEMA_VERSION

    def test_empty_name_rejected(self):
        with pytest.raises(ValueError, match="name must not be empty"):
            Profile("id", "", BigFive(70,65,45,70,30),
                    ResponseBias(0.18,0.31,0.52,0.81),
                    LinguisticTraits(0.42,0.68,0.57),
                    make_behavior(), "2026-01-01", 0)

    def test_negative_runs_rejected(self):
        with pytest.raises(ValueError, match="runs must be >= 0"):
            Profile("id", "john", BigFive(70,65,45,70,30),
                    ResponseBias(0.18,0.31,0.52,0.81),
                    LinguisticTraits(0.42,0.68,0.57),
                    make_behavior(), "2026-01-01", -1)

    def test_immutable(self):
        p = make_profile()
        with pytest.raises((AttributeError, TypeError)):
            p.name = "hacked"  # type: ignore


# ── Event tests ───────────────────────────────────────────────────────────────

class TestEvent:
    def test_valid(self):
        e = Event(EventType.FRAME_CHANGED, SOURCE_CAPTURE, {"region": [0,0,100,100]}, frame_id=1)
        assert e.event_type == EventType.FRAME_CHANGED
        assert e.source == SOURCE_CAPTURE

    def test_payload_frozen(self):
        e = Event(EventType.PAGE_LOADED, SOURCE_PERCEPTION, {"url": "https://x.com"})
        with pytest.raises(TypeError):
            e.payload["injected"] = "evil"  # type: ignore

    def test_invalid_source_rejected(self):
        with pytest.raises(ValueError, match="source must be one of"):
            Event(EventType.FRAME_CHANGED, "unknown_layer", {})

    def test_negative_frame_id_rejected(self):
        with pytest.raises(ValueError, match="frame_id must be >= 0"):
            Event(EventType.FRAME_CHANGED, SOURCE_CAPTURE, {}, frame_id=-1)

    def test_all_valid_sources_accepted(self):
        for src in (SOURCE_CAPTURE, SOURCE_PERCEPTION, SOURCE_ACTION,
                    SOURCE_FSM, SOURCE_REASONING, SOURCE_PERSISTENCE, SOURCE_SYSTEM):
            Event(EventType.STATE_TRANSITION, src, {})

    def test_zero_timestamp_rejected(self):
        with pytest.raises(ValueError, match="timestamp must be > 0"):
            Event(EventType.TIMEOUT, SOURCE_FSM, {}, timestamp=0)


# ── Error taxonomy tests ──────────────────────────────────────────────────────

class TestErrors:
    def test_base_error(self):
        e = CareerBridgeError(ErrorCode.SCHEMA_VALIDATION_FAILED, "bad schema")
        assert "[E902]" in str(e)
        assert e.code == ErrorCode.SCHEMA_VALIDATION_FAILED

    def test_context_default_empty(self):
        e = CareerBridgeError(ErrorCode.LLM_TIMEOUT, "timed out")
        assert e.context == {}

    def test_context_stored(self):
        e = StateError(ErrorCode.STATE_INVALID_TRANSITION, "bad",
                       {"from": "init", "to": "complete"})
        assert e.context["from"] == "init"

    def test_subclass_hierarchy(self):
        for cls in (CaptureError, PerceptionError, ActionError, StateError,
                    PersistenceError, LLMError, SOPError, ProfileError, SchemaError):
            inst = cls(ErrorCode.SCHEMA_VALIDATION_FAILED, "test")
            assert isinstance(inst, CareerBridgeError)

    def test_all_error_codes_have_string_value(self):
        for code in ErrorCode:
            assert code.value.startswith("E")
            assert len(code.value) == 4


# ── State machine transition tests ────────────────────────────────────────────

class TestStateMachine:
    def test_all_states_in_transition_table(self):
        for state in FSMState:
            assert state in VALID_TRANSITIONS, f"{state} missing from VALID_TRANSITIONS"

    def test_valid_transitions(self):
        valid = [
            (FSMState.INIT,     FSMState.NAVIGATE),
            (FSMState.INIT,     FSMState.ERROR),
            (FSMState.NAVIGATE, FSMState.WAIT_UI),
            (FSMState.NAVIGATE, FSMState.ERROR),
            (FSMState.WAIT_UI,  FSMState.EXTRACT),
            (FSMState.WAIT_UI,  FSMState.NAVIGATE),
            (FSMState.WAIT_UI,  FSMState.ERROR),
            (FSMState.EXTRACT,  FSMState.REASON),
            (FSMState.EXTRACT,  FSMState.ERROR),
            (FSMState.REASON,   FSMState.EXECUTE),
            (FSMState.REASON,   FSMState.ERROR),
            (FSMState.EXECUTE,  FSMState.VERIFY),
            (FSMState.EXECUTE,  FSMState.ERROR),
            (FSMState.VERIFY,   FSMState.EXECUTE),
            (FSMState.VERIFY,   FSMState.NAVIGATE),
            (FSMState.VERIFY,   FSMState.COMPLETE),
            (FSMState.VERIFY,   FSMState.ERROR),
            (FSMState.ERROR,    FSMState.NAVIGATE),
        ]
        for from_s, to_s in valid:
            assert is_valid_transition(from_s, to_s), f"Expected valid: {from_s} → {to_s}"

    def test_invalid_transitions(self):
        invalid = [
            (FSMState.INIT,     FSMState.COMPLETE),
            (FSMState.INIT,     FSMState.EXECUTE),
            (FSMState.NAVIGATE, FSMState.REASON),
            (FSMState.EXTRACT,  FSMState.EXECUTE),
            (FSMState.REASON,   FSMState.VERIFY),
            (FSMState.COMPLETE, FSMState.INIT),
            (FSMState.COMPLETE, FSMState.NAVIGATE),
            (FSMState.ERROR,    FSMState.COMPLETE),
            (FSMState.ERROR,    FSMState.INIT),
        ]
        for from_s, to_s in invalid:
            assert not is_valid_transition(from_s, to_s), f"Expected invalid: {from_s} → {to_s}"

    def test_complete_is_terminal(self):
        assert FSMState.COMPLETE in TERMINAL_STATES
        assert VALID_TRANSITIONS[FSMState.COMPLETE] == frozenset()

    def test_error_has_one_recovery_path(self):
        assert VALID_TRANSITIONS[FSMState.ERROR] == frozenset({FSMState.NAVIGATE})

    def test_assert_valid_transition_raises_state_error(self):
        with pytest.raises(StateError) as exc_info:
            assert_valid_transition(FSMState.INIT, FSMState.COMPLETE)
        assert exc_info.value.code == ErrorCode.STATE_INVALID_TRANSITION

    def test_assert_valid_transition_passes_silently(self):
        assert_valid_transition(FSMState.INIT, FSMState.NAVIGATE)  # no exception

    def test_execution_states_correct(self):
        assert FSMState.EXECUTE in EXECUTION_STATES
        assert FSMState.NAVIGATE not in EXECUTION_STATES
        assert FSMState.REASON not in EXECUTION_STATES

    def test_reasoning_states_correct(self):
        assert FSMState.REASON in REASONING_STATES
        assert FSMState.EXECUTE not in REASONING_STATES

    def test_perception_states_correct(self):
        assert FSMState.WAIT_UI in PERCEPTION_STATES
        assert FSMState.EXTRACT in PERCEPTION_STATES
        assert FSMState.EXECUTE not in PERCEPTION_STATES

    def test_reachable_from(self):
        reachable = reachable_from(FSMState.VERIFY)
        assert FSMState.EXECUTE in reachable
        assert FSMState.COMPLETE in reachable
        assert FSMState.NAVIGATE in reachable
        assert FSMState.INIT not in reachable

    def test_no_transition_skips_to_complete_from_init(self):
        # Can only reach COMPLETE via VERIFY
        for state in FSMState:
            if state == FSMState.VERIFY:
                continue
            assert FSMState.COMPLETE not in VALID_TRANSITIONS[state], \
                f"COMPLETE must only be reachable from VERIFY, not {state}"
