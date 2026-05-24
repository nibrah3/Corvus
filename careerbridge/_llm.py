"""LLM interface for the assessment pipeline — stateless, prompt-cached system prompt."""
from __future__ import annotations

import json
import os
import re as _re

from openai import OpenAI

_OPENROUTER_KEY = os.environ.get("OPENROUTER_API_KEY", "")
_MODEL = "anthropic/claude-sonnet-4-6"
_SYSTEM_PROMPT = (
    "You are completing a personality or skills assessment on behalf of a candidate. "
    "For each question on the page, select the answer that best matches the candidate's "
    "personality profile. "
    "Return ONLY a valid JSON array. Each object must have exactly two keys: "
    "'node_id' (string) and 'action' ('click' or 'type'). "
    "For 'type' actions include a third key 'text' with the answer string. "
    "One action per question. No markdown, no explanation."
)

# Roles that represent answerable interactive elements
ANSWERABLE_ROLES = frozenset({
    "radio", "checkbox", "button", "option", "menuitem",
    "menuitemcheckbox", "menuitemradio", "switch", "tab",
})
TEXT_INPUT_ROLES = frozenset({"textbox", "searchbox", "spinbutton"})
SUBMIT_NAMES = frozenset({"next", "continue", "submit", "save", "finish", "proceed"})


def call_llm(element_list: list[dict], profile_summary: str,
             page_context: str = "") -> list[dict]:
    client = OpenAI(api_key=_OPENROUTER_KEY, base_url="https://openrouter.ai/api/v1")
    payload = json.dumps({
        "candidate":     profile_summary,
        "page_context":  page_context[:3000] if page_context else "",
        "page_elements": element_list,
    }, ensure_ascii=False)
    resp = client.chat.completions.create(
        model=_MODEL,
        max_tokens=1024,
        messages=[
            {"role": "system", "content": _SYSTEM_PROMPT},
            {"role": "user",   "content": payload},
        ],
    )
    raw = (resp.choices[0].message.content or "").strip()
    if not raw:
        raise ValueError("LLM returned empty response")
    if raw.startswith("```"):
        raw = raw.split("\n", 1)[1].rsplit("```", 1)[0].strip()
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        pass
    m = _re.search(r"\[.*?\]", raw, _re.DOTALL)
    if m:
        return json.loads(m.group())
    raise ValueError(f"No JSON array found in LLM response (len={len(raw)})")


def profile_summary(profile) -> str:
    """Compact text summary of candidate profile for the LLM prompt."""
    parts = []
    if hasattr(profile, "name") and profile.name:
        parts.append(f"Name: {profile.name}")
    try:
        bf = profile.big_five
        parts.append(
            f"Big Five: O={bf.openness:.2f} C={bf.conscientiousness:.2f} "
            f"E={bf.extraversion:.2f} A={bf.agreeableness:.2f} N={bf.neuroticism:.2f}"
        )
    except Exception:
        pass
    return " | ".join(parts) or "No profile data"
