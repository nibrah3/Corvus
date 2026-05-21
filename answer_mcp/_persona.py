"""
Persona system for profile-level writing fingerprints.

Design:
  Each browser profile gets one persona, generated once and stored permanently.
  The persona is a blend of:
    - Facts provided by the user (age, background, industry) — asked contextually
      during whatever the user is doing, not through a fixed questionnaire
    - Style characteristics generated randomly by LLM — quirks, sentence starters,
      vocabulary patterns, hedging habits, personality colour

  Two profiles for the same user will write completely differently.
  The same profile always writes the same way.

Storage:
  D:\\cb-core\\profiles\\{profile_id}.json
  {
    "profile_id": "...",
    "facts": { "age": 31, "background": "...", "industry": "..." },
    "style": { ... LLM-generated style descriptor ... },
    "persona_prompt": "..."  -- the final system-prompt fragment used for generation
  }
"""
from __future__ import annotations

import json
import hashlib
import os
from pathlib import Path
from typing import Any

PROFILES_DIR = Path(__file__).parent.parent / "profiles"


def _profiles_dir() -> Path:
    PROFILES_DIR.mkdir(parents=True, exist_ok=True)
    return PROFILES_DIR


def _profile_path(profile_id: str) -> Path:
    safe = profile_id.replace("/", "_").replace("\\", "_")
    return _profiles_dir() / f"{safe}.json"


def load_profile(profile_id: str) -> dict:
    p = _profile_path(profile_id)
    if p.exists():
        return json.loads(p.read_text(encoding="utf-8"))
    return {}


def save_profile(profile_id: str, data: dict) -> None:
    p = _profile_path(profile_id)
    p.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")


def has_persona(profile_id: str) -> bool:
    prof = load_profile(profile_id)
    return bool(prof.get("persona_prompt"))


def get_persona_prompt(profile_id: str) -> str | None:
    prof = load_profile(profile_id)
    return prof.get("persona_prompt")


# ── Persona generation ────────────────────────────────────────────────────────

def generate_persona(profile_id: str, facts: dict[str, Any]) -> dict:
    """
    Generate a unique writing persona for this profile.

    facts: whatever the user has provided so far — age, background, industry,
           location, role, etc. Only what was naturally gathered; no fixed schema.

    Returns the full persona dict and saves it to the profile file.
    """
    # Deterministic seed from profile_id — same profile always gets same base seed
    # but facts (user-provided) shift the final result so two profiles with
    # identical facts still differ (different profile_id hash)
    seed_int = int(hashlib.sha256(profile_id.encode()).hexdigest()[:8], 16)

    facts_text = "\n".join(f"- {k}: {v}" for k, v in facts.items() if v)

    prompt = f"""
You are creating a unique writing persona for someone who will be taking professional
assessments and writing job application materials online.

Profile seed: {seed_int}

What we know about this person (provided by them):
{facts_text if facts_text else "- No specific details provided yet"}

Your task: Generate a highly specific, believable human writing persona for this profile.
The persona must be:
- Completely unique — not a generic archetype
- Grounded in the facts above (if age=28, the style should feel like a 28-year-old)
- Extremely human-sounding when used to generate text — no AI feel whatsoever
- Varied from other profiles (the seed above differentiates it)

Generate a JSON object with these exact keys:
{{
  "character_sketch": "2-3 sentence description of this person as a human being",
  "writing_voice": "one sentence describing how they write overall",
  "sentence_starters": ["3-5 phrases this person naturally starts sentences with"],
  "hedges": ["2-4 hedging phrases they use (or empty list if they're direct)"],
  "quirks": ["2-3 specific writing habits — e.g., 'uses sports analogies', 'underexplains then clarifies'"],
  "vocabulary_level": "casual / mixed / professional (pick one based on background)",
  "contraction_use": "always / usually / sometimes / rarely",
  "anecdote_tendency": "loves them / uses occasionally / avoids them",
  "formality_note": "one sentence on their specific formality register",
  "dont_do": ["2-3 things this persona would NEVER write — e.g., 'would never say Furthermore'"]
}}

Return ONLY the JSON. No preamble, no explanation.
""".strip()

    style = _call_llm(prompt)

    # Build the final persona prompt fragment used at generation time
    persona_prompt = _build_persona_prompt(facts, style)

    data = load_profile(profile_id)
    data.update({
        "profile_id":    profile_id,
        "facts":         facts,
        "style":         style,
        "persona_prompt": persona_prompt,
    })
    save_profile(profile_id, data)

    return data


def _build_persona_prompt(facts: dict, style: dict) -> str:
    """Construct the system-prompt fragment for text generation."""
    facts_lines = [f"{k}: {v}" for k, v in facts.items() if v]
    facts_block = "\n".join(facts_lines) if facts_lines else "not specified"

    starters = ", ".join(f'"{s}"' for s in style.get("sentence_starters", []))
    hedges = ", ".join(f'"{h}"' for h in style.get("hedges", []))
    quirks = "\n".join(f"- {q}" for q in style.get("quirks", []))
    dont = "\n".join(f"- {d}" for d in style.get("dont_do", []))

    return f"""
You are writing AS a specific person. Write exactly as they would — not as an AI,
not as a polished professional writer, but as this actual human being.

About them:
{facts_block}

Their character: {style.get("character_sketch", "")}

How they write:
{style.get("writing_voice", "")}

Their sentence starters (use these naturally): {starters}
Hedging style: {hedges if hedges else "direct, minimal hedging"}
Contraction use: {style.get("contraction_use", "usually")}
Anecdotes: {style.get("anecdote_tendency", "uses occasionally")}
Formality: {style.get("formality_note", "")}
Vocabulary: {style.get("vocabulary_level", "mixed")}

Specific quirks:
{quirks}

What they would NEVER write:
{dont}

Critical rules:
- Sound like THIS SPECIFIC PERSON, not a generic human
- No bullet points in prose answers
- No "Furthermore", "In conclusion", "It is worth noting"
- Vary sentence length — short punchy sentences mixed with longer ones
- Include natural imperfections in flow — thoughts develop, not pre-organized
- Write in first person unless the question asks otherwise
""".strip()


def _call_llm(prompt: str) -> dict:
    """Call OpenRouter to generate persona style dict."""
    import requests

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
            "messages": [{"role": "user", "content": prompt}],
            "response_format": {"type": "json_object"},
            "temperature": 1.0,  # max variation for unique personas
        },
        timeout=30,
    )
    r.raise_for_status()
    content = r.json()["choices"][0]["message"]["content"]
    return json.loads(content)
