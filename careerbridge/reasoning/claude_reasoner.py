# reasoning/claude_reasoner.py — Phase 9: Claude Answer Reasoner
# SCHEMA_VERSION: 1
#
# Single responsibility: translate UIState + Profile into a list of Actions
# by calling Claude to select which answer elements to click.
#
# Input:  UIState (structured perception output) + Profile (frozen personality kernel)
# Output: list[Action] — zero or more CLICK actions targeting answer elements
#
# MUST NOT: capture pixels, navigate UI, modify FSM state, execute actions.

from __future__ import annotations

import json
import os
import uuid

from openai import OpenAI

from ..errors import ErrorCode, LLMError
from ..schema import Action, Profile, UIState
from ..types import ActionType, ConfidenceBand, ElementType, confidence_band

_MODEL      = "anthropic/claude-haiku-4.5"
_BASE_URL   = "https://openrouter.ai/api/v1"
_MAX_TOKENS = 1024


def _client() -> OpenAI:
    key = os.getenv("OPENROUTER_API_KEY", "")
    if not key:
        raise LLMError(
            ErrorCode.LLM_TIMEOUT,
            "OPENROUTER_API_KEY not set in environment",
            {},
        )
    return OpenAI(api_key=key, base_url=_BASE_URL)

# Element types that represent selectable answer options
_ANSWER_TYPES = frozenset({
    ElementType.RADIO,
    ElementType.CHECKBOX,
    ElementType.BUTTON,
})


# ── Prompt construction ───────────────────────────────────────────────────────

def build_prompt(ui_state: UIState, profile: Profile) -> str:
    """
    Build a compact structured JSON prompt for Claude.
    Text-only — no images, no raw pixel data. LOW-confidence elements excluded.
    """
    elements = []
    for e in ui_state.elements:
        if confidence_band(e.confidence) == ConfidenceBand.LOW:
            continue
        elements.append({
            "id":   e.element_id,
            "type": e.element_type.value,
            "text": e.text,
        })

    payload = {
        "task": (
            "You are completing a personality or skills assessment on behalf of a candidate. "
            "Select the answer option that best matches the personality profile for each question. "
            "Return ONLY a valid JSON array of action objects. "
            "Each object must have exactly two keys: "
            "'element_id' (the string id of the element to click) and "
            "'action_type' (always the string 'click'). "
            "One action per question. No explanation, no markdown, no code fences."
        ),
        "personality": {
            "openness":                 profile.big_five.openness,
            "conscientiousness":        profile.big_five.conscientiousness,
            "extraversion":             profile.big_five.extraversion,
            "agreeableness":            profile.big_five.agreeableness,
            "neuroticism":              profile.big_five.neuroticism,
            "extreme_answer_rate":      profile.response_bias.extreme_answer_rate,
            "neutral_preference":       profile.response_bias.neutral_preference,
            "social_desirability_bias": profile.response_bias.social_desirability_bias,
            "consistency_strength":     profile.response_bias.consistency_strength,
        },
        "ui_elements": elements,
    }
    return json.dumps(payload, ensure_ascii=False)


# ── Response parsing ──────────────────────────────────────────────────────────

def parse_response(raw: str, ui_state: UIState, profile: Profile) -> list[Action]:
    """
    Parse and validate Claude's JSON response into Actions.

    Validates at the layer boundary — raises LLMError on any schema violation
    so the orchestrator can route to ERROR state cleanly.
    """
    # Strip markdown code fences — model may wrap despite instructions
    raw = raw.strip()
    if raw.startswith("```"):
        raw = raw.split("\n", 1)[1] if "\n" in raw else raw[3:]
        raw = raw.rsplit("```", 1)[0].strip()

    try:
        data = json.loads(raw)
    except json.JSONDecodeError as e:
        raise LLMError(
            ErrorCode.LLM_INVALID_RESPONSE,
            f"Claude response is not valid JSON: {e}",
            {"raw_preview": raw[:300]},
        )

    if not isinstance(data, list):
        raise LLMError(
            ErrorCode.LLM_INVALID_RESPONSE,
            f"Claude response must be a JSON array, got {type(data).__name__}",
            {"raw_preview": raw[:300]},
        )

    valid_ids = {e.element_id for e in ui_state.elements}
    actions: list[Action] = []

    for i, item in enumerate(data):
        if not isinstance(item, dict):
            raise LLMError(
                ErrorCode.LLM_INVALID_RESPONSE,
                f"Action at index {i} must be a dict, got {type(item).__name__}",
                {"index": i},
            )

        element_id     = item.get("element_id")
        action_type_s  = item.get("action_type")

        if not isinstance(element_id, str) or not element_id:
            raise LLMError(
                ErrorCode.LLM_INVALID_RESPONSE,
                f"Action[{i}]: 'element_id' must be a non-empty string, got {element_id!r}",
                {"index": i, "got": element_id},
            )
        if element_id not in valid_ids:
            raise LLMError(
                ErrorCode.LLM_INVALID_RESPONSE,
                f"Action[{i}]: element_id {element_id!r} not found in UIState",
                {"index": i, "element_id": element_id},
            )
        if action_type_s != "click":
            raise LLMError(
                ErrorCode.LLM_INVALID_RESPONSE,
                f"Action[{i}]: unsupported action_type {action_type_s!r} (only 'click' allowed)",
                {"index": i, "action_type": action_type_s},
            )

        actions.append(Action(
            action_id=f"llm-{uuid.uuid4().hex[:8]}",
            action_type=ActionType.CLICK,
            target_element_id=element_id,
            payload={},
            profile_id=profile.profile_id,
            frame_id=ui_state.frame_id,
        ))

    return actions


# ── Public ReasonerFn ─────────────────────────────────────────────────────────

def claude_reasoner(ui_state: UIState, profile: Profile) -> list[Action]:
    """
    ReasonerFn: calls Claude to select answer elements for the current UIState.

    Returns an empty list if no answerable (RADIO/CHECKBOX/BUTTON) elements exist
    above the LOW confidence threshold — the orchestrator will route to COMPLETE.

    Raises LLMError on API failure or malformed response; the orchestrator
    catches this and transitions to ERROR.
    """
    answerable = [
        e for e in ui_state.elements
        if e.element_type in _ANSWER_TYPES
        and confidence_band(e.confidence) != ConfidenceBand.LOW
    ]
    if not answerable:
        return []

    prompt = build_prompt(ui_state, profile)

    try:
        resp = _client().chat.completions.create(
            model=_MODEL,
            max_tokens=_MAX_TOKENS,
            messages=[{"role": "user", "content": prompt}],
        )
    except LLMError:
        raise
    except Exception as e:
        raise LLMError(
            ErrorCode.LLM_TIMEOUT,
            f"OpenRouter call failed: {e}",
            {"model": _MODEL},
        )

    raw = resp.choices[0].message.content if resp.choices else ""
    print(f"[reasoner] raw response ({len(raw)} chars): {raw[:500]!r}", flush=True)
    actions = parse_response(raw, ui_state, profile)
    elem_map = {e.element_id: e for e in ui_state.elements}
    for a in actions:
        elem = elem_map.get(a.target_element_id)
        txt = repr(elem.text[:80]) if elem else "?"
        print(f"[reasoner] selected id={a.target_element_id} bbox={elem.bbox if elem else '?'} text={txt}", flush=True)
    return actions
