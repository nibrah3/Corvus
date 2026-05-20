"""
Answer humanizer — generates text in the profile's locked persona voice.

The canonical answer (what is factually correct) is rewritten by the LLM
AS the persona. Each time the answer comes out differently because:
  1. A variation key (derived from question hash + timestamp) seeds the LLM
  2. The LLM has temperature=1.0 — full creative latitude within the persona
  3. The persona itself locks stylistic fingerprints (starters, quirks, hedges)

Result: two profiles answering the same question produce text that is
statistically different (different vocabulary distribution, structure,
sentence patterns) even though both answers are correct.
"""
from __future__ import annotations

import hashlib
import os
import time
import requests


def humanize(
    canonical_answer: str,
    question: str,
    persona_prompt: str,
    profile_id: str,
    target_words: int | None = None,
) -> str:
    """
    Rewrite canonical_answer in the profile's voice.

    Args:
        canonical_answer: The factually correct answer content.
        question:         The question being answered (gives context).
        persona_prompt:   The persona system-prompt fragment from _persona.py.
        profile_id:       Used to generate variation key.
        target_words:     Approximate word count target (None = match original).

    Returns:
        Human-sounding prose in the profile's voice.
    """
    # Variation key — changes per question+time so repeated calls differ
    vkey_src = f"{profile_id}:{question}:{int(time.time() // 300)}"
    variation_key = hashlib.sha256(vkey_src.encode()).hexdigest()[:12]

    word_instruction = ""
    if target_words:
        word_instruction = f"\nTarget length: approximately {target_words} words. Don't pad or cut — aim naturally."

    system = persona_prompt

    user_prompt = f"""
Question: {question}

The answer to express: {canonical_answer}

Variation key (internal — do not include in output): {variation_key}
{word_instruction}

Write the answer now, in this person's natural voice. Do not explain what you're doing.
Just write the answer as they would write it.
""".strip()

    return _call_llm(system, user_prompt)


def humanize_prose(
    text: str,
    context: str,
    persona_prompt: str,
    profile_id: str,
) -> str:
    """
    General-purpose rewrite of any text into the profile's voice.
    Used for cover letters, CV summaries, free-text fields.
    """
    vkey = hashlib.sha256(f"{profile_id}:{context}:{time.time():.0f}".encode()).hexdigest()[:12]

    user_prompt = f"""
Context: {context}

Text to rewrite: {text}

Variation key: {vkey}

Rewrite this in this person's natural voice. Same meaning, completely their style.
""".strip()

    return _call_llm(persona_prompt, user_prompt)


def _call_llm(system: str, user: str) -> str:
    api_key = os.environ.get("OPENROUTER_API_KEY", "")
    if not api_key:
        raise EnvironmentError("OPENROUTER_API_KEY not set")

    r = requests.post(
        "https://openrouter.ai/api/v1/chat/completions",
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        },
        json={
            "model": "anthropic/claude-sonnet-4-6",
            "messages": [
                {"role": "system", "content": system},
                {"role": "user",   "content": user},
            ],
            "temperature": 1.0,
        },
        timeout=45,
    )
    r.raise_for_status()
    return r.json()["choices"][0]["message"]["content"].strip()
