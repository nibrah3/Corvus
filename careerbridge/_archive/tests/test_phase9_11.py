# tests/test_phase9_11.py — Phase 9: Reasoner + Confidence Gating
# SCHEMA_VERSION: 1
#
# Coverage:
#   TestConfidenceBand      — confidence_band() conversion
#   TestBuildPrompt         — prompt JSON construction
#   TestParseResponse       — boundary validation of Claude's response
#   TestClaudeReasoner      — end-to-end reasoner with mocked API
#   TestOrchestratorGating  — confidence band gating in _handle_extract
#   TestOrchestratorVerify  — UI-change check in _handle_verify
#
# All tests are unit tests — zero live API calls, zero hardware required.

from __future__ import annotations

import json
import time
from typing import Optional
from unittest.mock import MagicMock, patch

import pytest

from careerbridge.errors import ErrorCode, LLMError
from careerbridge.fsm import AssessmentFSM
from careerbridge.orchestrator import AssessmentOrchestrator
from careerbridge.reasoning.claude_reasoner import (
    _MODEL,
    _MAX_TOKENS,
    build_prompt,
    claude_reasoner,
    parse_response,
)
from careerbridge.schema import (
    Action,
    BigFive,
    BehaviorFingerprint,
    BoundingBox,
    LinguisticTraits,
    Profile,
    ResponseBias,
    UIElement,
    UIState,
)
from careerbridge.types import (
    ActionType,
    ChangeType,
    ConfidenceBand,
    ElementType,
    FSMState,
    MouseSpeed,
    PerceptionSource,
    confidence_band,
)


# ── Shared fixtures ───────────────────────────────────────────────────────────

def _bbox(x: int = 0, y: int = 0, w: int = 100, h: int = 20) -> BoundingBox:
    return BoundingBox(x=x, y=y, w=w, h=h)


def _profile() -> Profile:
    return Profile(
        profile_id="test-p1",
        name="Test User",
        big_five=BigFive(
            openness=72, conscientiousness=65,
            extraversion=45, agreeableness=70, neuroticism=30,
        ),
        response_bias=ResponseBias(
            extreme_answer_rate=0.18, neutral_preference=0.31,
            social_desirability_bias=0.10, consistency_strength=0.80,
        ),
        linguistic_traits=LinguisticTraits(verbosity=0.4, formality=0.6, optimism=0.7),
        behavior=BehaviorFingerprint(
            typing_wpm=62, error_rate=0.03,
            mouse_speed=MouseSpeed.MEDIUM,
            pause_min_ms=100, pause_max_ms=500,
        ),
        created_at="2026-01-01T00:00:00Z",
        runs=0,
    )


def _element(
    element_type: ElementType = ElementType.RADIO,
    text: str = "Strongly Agree",
    confidence: float = 0.95,
    x: int = 0,
    y: int = 0,
    frame_id: int = 1,
) -> UIElement:
    return UIElement(
        element_type=element_type,
        text=text,
        bbox=_bbox(x=x, y=y),
        confidence=confidence,
        source=PerceptionSource.UIA,
        frame_id=frame_id,
    )


def _ui_state(elements: tuple = (), frame_id: int = 1) -> UIState:
    return UIState(
        frame_id=frame_id,
        timestamp=1.0,
        window_title="Test",
        window_bbox=_bbox(w=1920, h=1080),
        elements=elements,
    )


# ── TestConfidenceBand ────────────────────────────────────────────────────────

class TestConfidenceBand:
    def test_score_above_0_85_is_high(self):
        assert confidence_band(0.90) == ConfidenceBand.HIGH

    def test_score_exactly_0_86_is_high(self):
        assert confidence_band(0.86) == ConfidenceBand.HIGH

    def test_score_exactly_0_85_is_medium(self):
        # boundary: > 0.85 for HIGH, so 0.85 itself is MEDIUM
        assert confidence_band(0.85) == ConfidenceBand.MEDIUM

    def test_score_in_medium_range(self):
        assert confidence_band(0.75) == ConfidenceBand.MEDIUM

    def test_score_exactly_0_65_is_medium(self):
        # boundary: >= 0.65 for MEDIUM
        assert confidence_band(0.65) == ConfidenceBand.MEDIUM

    def test_score_0_64_is_low(self):
        assert confidence_band(0.64) == ConfidenceBand.LOW

    def test_score_zero_is_low(self):
        assert confidence_band(0.0) == ConfidenceBand.LOW

    def test_score_one_is_high(self):
        assert confidence_band(1.0) == ConfidenceBand.HIGH

    def test_score_0_5_is_low(self):
        assert confidence_band(0.50) == ConfidenceBand.LOW


# ── TestBuildPrompt ───────────────────────────────────────────────────────────

class TestBuildPrompt:
    def test_returns_valid_json(self):
        state = _ui_state((_element(),))
        result = build_prompt(state, _profile())
        parsed = json.loads(result)   # must not raise
        assert isinstance(parsed, dict)

    def test_personality_fields_present(self):
        state = _ui_state((_element(),))
        parsed = json.loads(build_prompt(state, _profile()))
        p = parsed["personality"]
        assert p["openness"] == 72
        assert p["conscientiousness"] == 65
        assert p["extraversion"] == 45
        assert p["agreeableness"] == 70
        assert p["neuroticism"] == 30
        assert p["extreme_answer_rate"] == 0.18
        assert p["neutral_preference"] == 0.31

    def test_high_confidence_element_included(self):
        elem = _element(confidence=0.95)
        state = _ui_state((elem,))
        parsed = json.loads(build_prompt(state, _profile()))
        ids = [e["id"] for e in parsed["ui_elements"]]
        assert elem.element_id in ids

    def test_medium_confidence_element_included(self):
        elem = _element(confidence=0.70)
        state = _ui_state((elem,))
        parsed = json.loads(build_prompt(state, _profile()))
        ids = [e["id"] for e in parsed["ui_elements"]]
        assert elem.element_id in ids

    def test_low_confidence_element_excluded(self):
        elem = _element(confidence=0.40)
        state = _ui_state((elem,))
        parsed = json.loads(build_prompt(state, _profile()))
        ids = [e["id"] for e in parsed["ui_elements"]]
        assert elem.element_id not in ids

    def test_element_has_required_fields(self):
        elem = _element(text="Agree")
        state = _ui_state((elem,))
        parsed = json.loads(build_prompt(state, _profile()))
        entry = parsed["ui_elements"][0]
        assert "id" in entry
        assert "type" in entry
        assert "text" in entry
        assert entry["text"] == "Agree"

    def test_task_instruction_present(self):
        state = _ui_state((_element(),))
        parsed = json.loads(build_prompt(state, _profile()))
        assert "task" in parsed
        assert "click" in parsed["task"]


# ── TestParseResponse ─────────────────────────────────────────────────────────

class TestParseResponse:
    def _state_with_radio(self) -> tuple[UIState, UIElement]:
        elem = _element(element_type=ElementType.RADIO, text="Agree", confidence=0.95)
        state = _ui_state((elem,))
        return state, elem

    def test_happy_path_single_action(self):
        state, elem = self._state_with_radio()
        raw = json.dumps([{"element_id": elem.element_id, "action_type": "click"}])
        actions = parse_response(raw, state, _profile())
        assert len(actions) == 1
        assert actions[0].action_type == ActionType.CLICK
        assert actions[0].target_element_id == elem.element_id

    def test_happy_path_multiple_actions(self):
        e1 = _element(text="Option A", confidence=0.9, x=0)
        e2 = _element(text="Option B", confidence=0.9, x=200)
        state = _ui_state((e1, e2))
        raw = json.dumps([
            {"element_id": e1.element_id, "action_type": "click"},
            {"element_id": e2.element_id, "action_type": "click"},
        ])
        actions = parse_response(raw, state, _profile())
        assert len(actions) == 2

    def test_empty_array_returns_empty_list(self):
        state = _ui_state((_element(),))
        actions = parse_response("[]", state, _profile())
        assert actions == []

    def test_invalid_json_raises_llm_error(self):
        state = _ui_state((_element(),))
        with pytest.raises(LLMError) as exc_info:
            parse_response("not json at all", state, _profile())
        assert exc_info.value.code == ErrorCode.LLM_INVALID_RESPONSE

    def test_not_array_raises_llm_error(self):
        state = _ui_state((_element(),))
        with pytest.raises(LLMError) as exc_info:
            parse_response('{"element_id": "x", "action_type": "click"}', state, _profile())
        assert exc_info.value.code == ErrorCode.LLM_INVALID_RESPONSE

    def test_item_not_dict_raises_llm_error(self):
        state = _ui_state((_element(),))
        with pytest.raises(LLMError):
            parse_response('["just a string"]', state, _profile())

    def test_missing_element_id_raises_llm_error(self):
        state, elem = self._state_with_radio()
        raw = json.dumps([{"action_type": "click"}])
        with pytest.raises(LLMError):
            parse_response(raw, state, _profile())

    def test_element_id_wrong_type_raises_llm_error(self):
        state, elem = self._state_with_radio()
        raw = json.dumps([{"element_id": 12345, "action_type": "click"}])
        with pytest.raises(LLMError):
            parse_response(raw, state, _profile())

    def test_empty_element_id_raises_llm_error(self):
        state, elem = self._state_with_radio()
        raw = json.dumps([{"element_id": "", "action_type": "click"}])
        with pytest.raises(LLMError):
            parse_response(raw, state, _profile())

    def test_unknown_element_id_raises_llm_error(self):
        state, elem = self._state_with_radio()
        raw = json.dumps([{"element_id": "nonexistent0000", "action_type": "click"}])
        with pytest.raises(LLMError):
            parse_response(raw, state, _profile())

    def test_unsupported_action_type_raises_llm_error(self):
        state, elem = self._state_with_radio()
        raw = json.dumps([{"element_id": elem.element_id, "action_type": "type"}])
        with pytest.raises(LLMError):
            parse_response(raw, state, _profile())

    def test_action_type_is_click(self):
        state, elem = self._state_with_radio()
        raw = json.dumps([{"element_id": elem.element_id, "action_type": "click"}])
        actions = parse_response(raw, state, _profile())
        assert actions[0].action_type == ActionType.CLICK

    def test_action_profile_id_matches(self):
        state, elem = self._state_with_radio()
        raw = json.dumps([{"element_id": elem.element_id, "action_type": "click"}])
        prof = _profile()
        actions = parse_response(raw, state, prof)
        assert actions[0].profile_id == prof.profile_id

    def test_action_frame_id_matches(self):
        state, elem = self._state_with_radio()
        raw = json.dumps([{"element_id": elem.element_id, "action_type": "click"}])
        actions = parse_response(raw, state, _profile())
        assert actions[0].frame_id == state.frame_id


# ── TestClaudeReasoner ────────────────────────────────────────────────────────

def _mock_api_response(text: str):
    msg = MagicMock()
    msg.content = [MagicMock(text=text)]
    return msg


class TestClaudeReasoner:
    def test_no_answerable_elements_returns_empty(self):
        # Only TEXT elements — nothing to click
        elem = _element(element_type=ElementType.TEXT, confidence=0.95)
        state = _ui_state((elem,))
        result = claude_reasoner(state, _profile())
        assert result == []

    def test_all_answerable_elements_low_confidence_returns_empty(self):
        elem = _element(element_type=ElementType.RADIO, confidence=0.30)
        state = _ui_state((elem,))
        result = claude_reasoner(state, _profile())
        assert result == []

    def test_happy_path_returns_actions(self):
        elem = _element(element_type=ElementType.RADIO, confidence=0.95)
        state = _ui_state((elem,))
        raw = json.dumps([{"element_id": elem.element_id, "action_type": "click"}])
        mock_resp = _mock_api_response(raw)

        with patch("careerbridge.reasoning.claude_reasoner.anthropic.Anthropic") as MockClient:
            MockClient.return_value.messages.create.return_value = mock_resp
            actions = claude_reasoner(state, _profile())

        assert len(actions) == 1
        assert actions[0].target_element_id == elem.element_id

    def test_api_exception_raises_llm_error(self):
        elem = _element(element_type=ElementType.RADIO, confidence=0.95)
        state = _ui_state((elem,))

        with patch("careerbridge.reasoning.claude_reasoner.anthropic.Anthropic") as MockClient:
            MockClient.return_value.messages.create.side_effect = RuntimeError("network down")
            with pytest.raises(LLMError) as exc_info:
                claude_reasoner(state, _profile())
        assert exc_info.value.code == ErrorCode.LLM_TIMEOUT

    def test_malformed_json_from_api_raises_llm_error(self):
        elem = _element(element_type=ElementType.RADIO, confidence=0.95)
        state = _ui_state((elem,))
        mock_resp = _mock_api_response("```json\nnot valid\n```")

        with patch("careerbridge.reasoning.claude_reasoner.anthropic.Anthropic") as MockClient:
            MockClient.return_value.messages.create.return_value = mock_resp
            with pytest.raises(LLMError):
                claude_reasoner(state, _profile())

    def test_correct_model_used(self):
        elem = _element(element_type=ElementType.RADIO, confidence=0.95)
        state = _ui_state((elem,))
        raw = json.dumps([{"element_id": elem.element_id, "action_type": "click"}])

        with patch("careerbridge.reasoning.claude_reasoner.anthropic.Anthropic") as MockClient:
            MockClient.return_value.messages.create.return_value = _mock_api_response(raw)
            claude_reasoner(state, _profile())
            call_kwargs = MockClient.return_value.messages.create.call_args
        assert call_kwargs.kwargs["model"] == _MODEL

    def test_correct_max_tokens(self):
        elem = _element(element_type=ElementType.RADIO, confidence=0.95)
        state = _ui_state((elem,))
        raw = json.dumps([{"element_id": elem.element_id, "action_type": "click"}])

        with patch("careerbridge.reasoning.claude_reasoner.anthropic.Anthropic") as MockClient:
            MockClient.return_value.messages.create.return_value = _mock_api_response(raw)
            claude_reasoner(state, _profile())
            call_kwargs = MockClient.return_value.messages.create.call_args
        assert call_kwargs.kwargs["max_tokens"] == _MAX_TOKENS

    def test_prompt_contains_personality_data(self):
        elem = _element(element_type=ElementType.RADIO, confidence=0.95)
        state = _ui_state((elem,))
        raw = json.dumps([{"element_id": elem.element_id, "action_type": "click"}])
        captured_prompt = []

        def capture(*args, **kwargs):
            captured_prompt.append(kwargs["messages"][0]["content"])
            return _mock_api_response(raw)

        with patch("careerbridge.reasoning.claude_reasoner.anthropic.Anthropic") as MockClient:
            MockClient.return_value.messages.create.side_effect = capture
            claude_reasoner(state, _profile())

        payload = json.loads(captured_prompt[0])
        assert payload["personality"]["openness"] == 72
        assert payload["personality"]["conscientiousness"] == 65

    def test_empty_api_content_raises_llm_error(self):
        elem = _element(element_type=ElementType.RADIO, confidence=0.95)
        state = _ui_state((elem,))
        mock_resp = MagicMock()
        mock_resp.content = []   # empty content list

        with patch("careerbridge.reasoning.claude_reasoner.anthropic.Anthropic") as MockClient:
            MockClient.return_value.messages.create.return_value = mock_resp
            with pytest.raises(LLMError):
                claude_reasoner(state, _profile())


# ── Helpers for orchestrator unit tests ──────────────────────────────────────

def _make_orchestrator(dry_run: bool = True) -> AssessmentOrchestrator:
    return AssessmentOrchestrator(
        window_title="Test",
        profile=_profile(),
        dry_run=dry_run,
        loop_timeout_s=5.0,
        wait_ui_timeout_s=1.0,
        poll_interval_s=0.01,
    )


def _fake_frame():
    """Return a minimal CaptureFrame-like mock."""
    import numpy as np
    from careerbridge.capture import CaptureBackend, CaptureFrame
    return CaptureFrame(
        frame_id=1,
        timestamp=time.monotonic(),
        window_title="Test",
        window_bbox=BoundingBox(x=0, y=0, w=800, h=600),
        data=np.zeros((600, 800, 4), dtype="uint8"),
        region=None,
        backend=CaptureBackend.MSS,
    )


# ── TestOrchestratorGating ────────────────────────────────────────────────────

class TestOrchestratorGating:
    """Tests for confidence band gating in _handle_extract."""

    def _run_extract(self, elements: list[UIElement]):
        """Drive the orchestrator just through the EXTRACT state."""
        orch = _make_orchestrator()
        frame = _fake_frame()

        with patch("careerbridge.orchestrator.extract_uia_elements", return_value=elements), \
             patch("careerbridge.orchestrator.extract_ocr_elements", return_value=[]):
            orch.fsm.transition(FSMState.NAVIGATE, "test setup")
            orch.fsm.transition(FSMState.WAIT_UI,  "test setup")
            orch.fsm.transition(FSMState.EXTRACT,  "test setup")
            mock_session = MagicMock()
            mock_session.grab.return_value = frame
            orch._handle_extract(mock_session, frame)

        return orch.fsm.state

    def test_all_low_confidence_goes_to_error(self):
        elements = [_element(confidence=0.40), _element(confidence=0.50)]
        assert self._run_extract(elements) == FSMState.ERROR

    def test_zero_elements_passes_through(self):
        # Zero elements → passes to REASON (reasoner returns [], routes to COMPLETE)
        assert self._run_extract([]) == FSMState.REASON

    def test_all_high_confidence_transitions_to_reason(self):
        elements = [_element(confidence=0.95), _element(confidence=0.90)]
        assert self._run_extract(elements) == FSMState.REASON

    def test_medium_confidence_passes(self):
        elements = [_element(confidence=0.70)]
        assert self._run_extract(elements) == FSMState.REASON

    def test_mixed_confidence_filters_low_and_passes(self):
        high_elem = _element(confidence=0.95, text="High", x=0)
        low_elem  = _element(confidence=0.40, text="Low",  x=200)
        elements = [high_elem, low_elem]

        orch = _make_orchestrator()
        frame = _fake_frame()

        with patch("careerbridge.orchestrator.extract_uia_elements", return_value=elements), \
             patch("careerbridge.orchestrator.extract_ocr_elements", return_value=[]):
            orch.fsm.transition(FSMState.NAVIGATE, "setup")
            orch.fsm.transition(FSMState.WAIT_UI,  "setup")
            orch.fsm.transition(FSMState.EXTRACT,  "setup")
            mock_session = MagicMock()
            mock_session.grab.return_value = frame
            orch._handle_extract(mock_session, frame)

        assert orch.fsm.state == FSMState.REASON
        ui_state = orch.fsm.get_context("ui_state")
        # LOW element filtered out — only high_elem should remain
        assert len(ui_state.elements) == 1
        assert ui_state.elements[0].element_id == high_elem.element_id

    def test_transition_reason_shows_filtered_count(self):
        high_elem = _element(confidence=0.95, text="High", x=0)
        low_elem  = _element(confidence=0.40, text="Low",  x=200)
        elements = [high_elem, low_elem]

        orch = _make_orchestrator()
        frame = _fake_frame()

        with patch("careerbridge.orchestrator.extract_uia_elements", return_value=elements), \
             patch("careerbridge.orchestrator.extract_ocr_elements", return_value=[]):
            orch.fsm.transition(FSMState.NAVIGATE, "setup")
            orch.fsm.transition(FSMState.WAIT_UI,  "setup")
            orch.fsm.transition(FSMState.EXTRACT,  "setup")
            mock_session = MagicMock()
            mock_session.grab.return_value = frame
            orch._handle_extract(mock_session, frame)

        last_transition = orch.fsm.history[-1]
        assert "filtered" in last_transition.reason


# ── TestOrchestratorVerify ────────────────────────────────────────────────────

class TestOrchestratorVerify:
    """Tests for UI-change verification in _handle_verify."""

    def _setup_verify(
        self,
        action_type: ActionType = ActionType.CLICK,
        change_type: Optional[ChangeType] = ChangeType.CONTENT,
        action_success: bool = True,
        has_more_actions: bool = False,
    ) -> AssessmentOrchestrator:
        from careerbridge.actions import ActionResult
        orch = _make_orchestrator()

        # Advance FSM to VERIFY
        orch.fsm.transition(FSMState.NAVIGATE, "setup")
        orch.fsm.transition(FSMState.WAIT_UI,  "setup")
        orch.fsm.transition(FSMState.EXTRACT,  "setup")
        orch.fsm.transition(FSMState.REASON,   "setup")
        orch.fsm.transition(FSMState.EXECUTE,  "setup")
        orch.fsm.transition(FSMState.VERIFY,   "setup")

        elem = _element(confidence=0.95)
        state = _ui_state((elem,))
        orch.fsm.set_context("ui_state", state)

        action = Action(
            action_id="test-a1",
            action_type=action_type,
            target_element_id=elem.element_id,
            payload={"text": "hello"} if action_type == ActionType.TYPE else {},
            profile_id=_profile().profile_id,
            frame_id=1,
        )
        orch.fsm.set_context("last_action_type", action_type)
        orch.fsm.set_context("last_action_change_type", change_type)
        orch.fsm.set_context(
            "last_action_result",
            ActionResult(
                success=action_success,
                action_id="test-a1",
                elapsed_ms=5.0,
                error_code=None if action_success else ErrorCode.ACTION_CLICK_UNVERIFIED,
                error_message=None if action_success else "fail",
            ),
        )
        if has_more_actions:
            orch.fsm.set_context("pending_actions", [action, action])
            orch.fsm.set_context("action_index", 1)
        else:
            orch.fsm.set_context("pending_actions", [action])
            orch.fsm.set_context("action_index", 1)

        return orch

    def test_click_with_change_none_goes_to_error(self):
        orch = self._setup_verify(
            action_type=ActionType.CLICK,
            change_type=ChangeType.NONE,
        )
        orch._handle_verify()
        assert orch.fsm.state == FSMState.ERROR

    def test_click_with_content_change_proceeds(self):
        orch = self._setup_verify(
            action_type=ActionType.CLICK,
            change_type=ChangeType.CONTENT,
        )
        orch._handle_verify()
        assert orch.fsm.state == FSMState.COMPLETE

    def test_click_with_minor_change_proceeds(self):
        orch = self._setup_verify(
            action_type=ActionType.CLICK,
            change_type=ChangeType.MINOR,
        )
        orch._handle_verify()
        assert orch.fsm.state == FSMState.COMPLETE

    def test_non_click_no_change_does_not_error(self):
        # TYPE action with no stored change_type — should not trigger change check
        orch = self._setup_verify(
            action_type=ActionType.TYPE,
            change_type=ChangeType.NONE,
        )
        orch._handle_verify()
        assert orch.fsm.state != FSMState.ERROR

    def test_none_change_type_stored_does_not_error(self):
        # Snap failed — change_type is None, should not false-negative
        orch = self._setup_verify(
            action_type=ActionType.CLICK,
            change_type=None,
        )
        orch._handle_verify()
        assert orch.fsm.state != FSMState.ERROR

    def test_action_result_failure_checked_first(self):
        # Even if change_type would be fine, a failed action result → ERROR
        orch = self._setup_verify(
            action_type=ActionType.CLICK,
            change_type=ChangeType.CONTENT,
            action_success=False,
        )
        orch._handle_verify()
        assert orch.fsm.state == FSMState.ERROR

    def test_click_no_change_errors_even_with_more_pending(self):
        orch = self._setup_verify(
            action_type=ActionType.CLICK,
            change_type=ChangeType.NONE,
            has_more_actions=True,
        )
        orch._handle_verify()
        assert orch.fsm.state == FSMState.ERROR

    def test_click_with_structural_change_proceeds(self):
        orch = self._setup_verify(
            action_type=ActionType.CLICK,
            change_type=ChangeType.STRUCTURAL,
        )
        orch._handle_verify()
        # STRUCTURAL change means page transitioned — COMPLETE or NAVIGATE
        assert orch.fsm.state in (FSMState.COMPLETE, FSMState.NAVIGATE, FSMState.EXECUTE)
