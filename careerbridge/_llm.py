"""LLM interface for the assessment pipeline.

Uses Anthropic SDK directly — no OpenRouter routing.
API key priority:
  1. ANTHROPIC_API_KEY  (direct Anthropic)
  2. OPENROUTER_API_KEY (fallback for legacy setups)
"""
from __future__ import annotations

import json
import os
import re as _re

_ANTHROPIC_KEY   = os.environ.get("ANTHROPIC_API_KEY", "")
_OPENROUTER_KEY  = os.environ.get("OPENROUTER_API_KEY", "")
_MODEL           = "claude-sonnet-4-6"            # Anthropic model ID
_OR_MODEL        = "anthropic/claude-sonnet-4-6"  # OpenRouter model ID (fallback)

_SYSTEM_PROMPT = (
    "You are completing a personality or skills assessment on behalf of a specific real person. "
    "Your job is to give the BEST, most correct answer to every question — "
    "answers that are accurate, appropriate, and authentically reflect this person's "
    "background, experience, and character. "
    "Different people answer the same question from different angles based on who they are. "
    "Use the candidate profile and persona to answer from their genuine perspective — "
    "not a generic or average perspective. "
    "Never deliberately choose a wrong or suboptimal answer. "
    "Return ONLY a valid JSON array. Each object must have exactly two keys: "
    "'node_id' (string) and 'action' ('click' or 'type'). "
    "For 'type' actions include a third key 'text' with the answer string. "
    "One action per question. No markdown, no explanation."
)


def _make_client():
    """Return an Anthropic client, falling back to OpenRouter if no Anthropic key."""
    if _ANTHROPIC_KEY:
        import anthropic
        return ("anthropic", anthropic.Anthropic(api_key=_ANTHROPIC_KEY))
    if _OPENROUTER_KEY:
        from openai import OpenAI
        return ("openrouter", OpenAI(api_key=_OPENROUTER_KEY,
                                     base_url="https://openrouter.ai/api/v1"))
    raise RuntimeError(
        "No LLM API key found. Set ANTHROPIC_API_KEY in D:\\cb-core\\.env"
    )


def call_llm(element_list: list[dict], candidate_summary: str,
             page_context: str = "",
             persona_prompt: str = "") -> list[dict]:
    client_type, client = _make_client()

    user_content: dict = {
        "candidate":     candidate_summary,
        "page_context":  page_context[:3000] if page_context else "",
        "page_elements": element_list,
    }
    if persona_prompt:
        user_content["persona"] = persona_prompt[:2000]

    user_msg = json.dumps(user_content, ensure_ascii=False)

    if client_type == "anthropic":
        resp = client.messages.create(
            model=_MODEL,
            max_tokens=1024,
            system=_SYSTEM_PROMPT,
            messages=[{"role": "user", "content": user_msg}],
        )
        raw = (resp.content[0].text or "").strip()
    else:
        resp = client.chat.completions.create(
            model=_OR_MODEL,
            max_tokens=1024,
            messages=[
                {"role": "system", "content": _SYSTEM_PROMPT},
                {"role": "user",   "content": user_msg},
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
    def _get(key: str, default=""):
        if isinstance(profile, dict):
            return profile.get(key) or default
        return getattr(profile, key, None) or default

    parts = []
    name = _get("name")
    if name:
        parts.append(f"Name: {name}")
    for field in ("location", "bio", "industry", "background"):
        val = _get(field)
        if val:
            parts.append(f"{field.capitalize()}: {str(val)[:200]}")
    skills = _get("skills")
    if skills:
        if isinstance(skills, list):
            parts.append(f"Skills: {', '.join(str(s) for s in skills[:12])}")
        else:
            parts.append(f"Skills: {str(skills)[:200]}")
    exp = _get("experience")
    if exp:
        parts.append(f"Experience: {str(exp)[:300]}")
    edu = _get("education")
    if edu:
        parts.append(f"Education: {str(edu)[:150]}")
    try:
        bf = profile.big_five
        parts.append(
            f"Big Five: O={bf.openness:.2f} C={bf.conscientiousness:.2f} "
            f"E={bf.extraversion:.2f} A={bf.agreeableness:.2f} N={bf.neuroticism:.2f}"
        )
    except Exception:
        pass
    return " | ".join(parts) or "No profile data"
