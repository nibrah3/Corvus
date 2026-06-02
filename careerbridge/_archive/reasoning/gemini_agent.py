# gemini_agent.py — Gemini Flash visual agent
# SCHEMA_VERSION: 2
#
# Single responsibility: take a screenshot, ask Gemini Flash what to do next,
# return a parsed action dict. Handles navigation AND answer/typing selection.
#
# MUST NOT: execute actions, capture pixels, modify FSM state.

from __future__ import annotations

import base64
import json
import os
import sys
import time
from io import BytesIO
from typing import Optional

import numpy as np

_MODEL    = "google/gemini-2.5-flash"
_BASE_URL = "https://openrouter.ai/api/v1"

# Ensure D:\cb-core is importable for answer_mcp sub-packages
_CB_ROOT = os.path.normpath(os.path.join(os.path.dirname(__file__), "..", ".."))
if _CB_ROOT not in sys.path:
    sys.path.insert(0, _CB_ROOT)


def _client():
    from openai import OpenAI
    key = os.getenv("OPENROUTER_API_KEY", "")
    if not key:
        raise RuntimeError("OPENROUTER_API_KEY not set")
    return OpenAI(api_key=key, base_url=_BASE_URL)


def _bgra_to_png_b64(data: np.ndarray) -> str:
    """Convert BGRA numpy array to base64-encoded PNG string."""
    from PIL import Image
    rgb = data[:, :, [2, 1, 0]]  # BGRA → RGB
    img = Image.fromarray(rgb)
    buf = BytesIO()
    img.save(buf, format="PNG")
    return base64.b64encode(buf.getvalue()).decode()


_SYSTEM = (
    "You are an AI agent controlling a browser to complete online assessments. "
    "You see screenshots and decide exactly one action at a time. "
    "Be deliberate and precise with pixel coordinates."
)

_SCHEMA = """{
  "action": "click" | "scroll" | "type" | "wait" | "complete",
  "x": <integer pixel x within the screenshot, required for click/type>,
  "y": <integer pixel y within the screenshot, required for click/type>,
  "text": "<prose text to type, only for type action>",
  "scroll_direction": "down" | "up",
  "scroll_amount": <integer 1-5, number of scroll wheel clicks>,
  "target": "<short description of element or reason>",
  "reasoning": "<one sentence>"
}"""


def _ensure_persona(profile_id: str) -> str:
    """Return persona_prompt for profile, auto-generating if missing."""
    from answer_mcp._persona import get_persona_prompt, generate_persona
    prompt = get_persona_prompt(profile_id)
    if not prompt:
        print(f"[gemini] auto-generating persona for profile {profile_id!r}", flush=True)
        data = generate_persona(profile_id, {})
        prompt = data["persona_prompt"]
    return prompt


def _apply_persona(text: str, question_context: str, profile_id: str) -> str:
    """Rewrite text in the profile's locked persona voice."""
    from answer_mcp._humanize import humanize
    persona_prompt = _ensure_persona(profile_id)
    return humanize(
        canonical_answer=text,
        question=question_context or "professional assessment question",
        persona_prompt=persona_prompt,
        profile_id=profile_id,
        target_words=len(text.split()) if text else None,
    )


def decide(
    screenshot_bgra: np.ndarray,
    win_x: int,
    win_y: int,
    personality: Optional[dict] = None,
    mode: str = "comprehension",
    profile_id: Optional[str] = None,
) -> dict:
    """
    Send a screenshot to Gemini Flash and get the next action.

    Args:
        screenshot_bgra: BGRA numpy array of the browser window.
        win_x, win_y:    Screen position of the window top-left (coord offset).
        personality:     Personality profile dict (assessment mode only).
        mode:            "assessment" | "comprehension"

    Returns:
        Action dict. x/y are converted to SCREEN-absolute coordinates.
        Includes "_latency_ms" key with round-trip time.
    """
    b64 = _bgra_to_png_b64(screenshot_bgra)
    h, w = screenshot_bgra.shape[:2]

    if mode == "comprehension":
        context = (
            "This is a reading comprehension test. "
            "Read the passage shown on screen carefully and answer each question accurately. "
            "For open text / long-response fields: click the field first (return action 'click'), "
            "then on the next step type a clear prose answer of ~30 words (action 'type'). "
            "Do not copy sentences verbatim — paraphrase and explain in your own words."
        )
    else:
        context = (
            "This is a personality or skills assessment.\n"
            f"Candidate personality profile:\n{json.dumps(personality or {}, indent=2)}\n\n"
            "Select the answer option that best matches the personality profile."
        )

    prompt = f"""Screenshot: {w}x{h} pixels of a browser window.

{context}

Decision rules (apply in order):
1. Page still loading → action "wait"
2. Start / Begin / Instructions page → click the start button
3. Text input or textarea is empty and needs an answer → action "type" with ~30 word prose answer (click it first if not focused)
4. Radio button / checkbox question → click the correct option
5. Next / Continue / Submit button visible after answering → click it
6. More content below the visible area → action "scroll" direction "down"
7. Test finished / thank-you / results page → action "complete"

Return ONLY valid JSON matching this schema exactly (no markdown, no code fences):
{_SCHEMA}

Coordinates are pixel positions within this screenshot image (top-left = 0,0)."""

    client = _client()
    t0 = time.monotonic()
    resp = client.chat.completions.create(
        model=_MODEL,
        max_tokens=600,
        messages=[
            {"role": "system", "content": _SYSTEM},
            {
                "role": "user",
                "content": [
                    {
                        "type": "image_url",
                        "image_url": {"url": f"data:image/png;base64,{b64}"},
                    },
                    {"type": "text", "text": prompt},
                ],
            },
        ],
    )
    latency_ms = round((time.monotonic() - t0) * 1000)

    raw = resp.choices[0].message.content if resp.choices else ""
    raw = raw.strip()
    if raw.startswith("```"):
        raw = raw.split("\n", 1)[1] if "\n" in raw else raw[3:]
        raw = raw.rsplit("```", 1)[0].strip()

    action = json.loads(raw)
    action["_latency_ms"] = latency_ms

    # Route type-action text through persona humanizer if profile_id is set.
    # Factual content from Gemini is preserved as canonical; only voice/style changes.
    if profile_id and action.get("action") == "type" and action.get("text"):
        canonical = action["text"]
        q_context = (action.get("target") or "") + " — " + (action.get("reasoning") or "")
        try:
            action["text"] = _apply_persona(canonical, q_context.strip(" —"), profile_id)
            print(f"[gemini] persona applied for profile {profile_id!r}", flush=True)
        except Exception as _pe:
            print(f"[gemini] persona humanize failed ({_pe}) — using raw text", flush=True)

    print(
        f"[gemini] {latency_ms}ms | action={action.get('action')} "
        f"target={action.get('target','?')!r} | {action.get('reasoning','')!r}",
        flush=True,
    )

    # Convert screenshot-relative coords to screen-absolute
    for key in ("x", "y"):
        if action.get(key) is not None:
            action[key] = int(action[key]) + (win_x if key == "x" else win_y)

    return action
