"""
Answer MCP server — persona management and human-voice text generation.

Tools:
  assign_persona      Generate and lock a writing persona for a profile
  get_persona         Retrieve a stored persona (check if one exists)
  update_persona_facts  Add/update facts for a profile (called as more info is gathered)
  humanize_answer     Write an assessment answer in the profile's voice
  humanize_prose      Rewrite any text (CV, cover letter) in the profile's voice

Persona design:
  Facts (age, background, industry, etc.) are gathered naturally during conversation
  — NOT through a fixed questionnaire. Whatever the user volunteers is enough.
  The LLM generates style characteristics (quirks, starters, hedging patterns)
  on top of those facts using a seed derived from the profile_id.

  The same profile_id always produces the same persona.
  Different profile_ids produce different personas even with identical facts.
"""
from __future__ import annotations

from typing import Optional, Any

from _minmcp import MinMCP

mcp = MinMCP("answer")


@mcp.tool()
def assign_persona(profile_id: str, facts: dict) -> dict:
    """
    Generate and permanently store a writing persona for this profile.

    Call this once when a new browser profile is registered.
    The persona is derived from whatever facts are available — there is no
    required set. Age, background, industry, role, location — use whatever
    the user has naturally shared. The more context, the more grounded the persona.

    Args:
        profile_id: The browser profile identifier (e.g. IXBrowser profile ID,
                    GoLogin profile ID, or any unique string).
        facts:      Dict of user-provided info. Any keys are valid.
                    Common: {"age": 28, "background": "marketing manager",
                             "industry": "fintech", "location": "Nairobi"}
                    Partial is fine: {"age": 31} works too.

    Returns:
        {profile_id, persona_prompt (excerpt), style_summary, saved: bool}
    """
    try:
        from answer_mcp._persona import generate_persona
        data = generate_persona(profile_id=profile_id, facts=facts)
        style = data.get("style", {})
        return {
            "profile_id":    profile_id,
            "saved":         True,
            "style_summary": style.get("character_sketch", ""),
            "voice":         style.get("writing_voice", ""),
            "quirks":        style.get("quirks", []),
        }
    except Exception as exc:
        return {"error": str(exc), "saved": False}


@mcp.tool()
def get_persona(profile_id: str) -> dict:
    """
    Retrieve the stored persona for a profile.

    Returns:
        {exists: bool, facts, style, persona_prompt}
        If no persona has been assigned: {exists: False}
    """
    try:
        from answer_mcp._persona import load_profile, has_persona
        if not has_persona(profile_id):
            return {"exists": False, "profile_id": profile_id}
        data = load_profile(profile_id)
        return {
            "exists":         True,
            "profile_id":     profile_id,
            "facts":          data.get("facts", {}),
            "style":          data.get("style", {}),
            "persona_prompt": data.get("persona_prompt", ""),
        }
    except Exception as exc:
        return {"error": str(exc)}


@mcp.tool()
def update_persona_facts(profile_id: str, new_facts: dict) -> dict:
    """
    Add or update factual information for a profile and regenerate the persona.

    Call this when the user provides more details about themselves during
    any interaction — not just onboarding. The persona is regenerated
    to incorporate the new facts while keeping the same style seed.

    Args:
        profile_id: Profile identifier.
        new_facts:  New or updated key-value pairs to merge into existing facts.

    Returns:
        {updated: bool, facts (merged), style_summary}
    """
    try:
        from answer_mcp._persona import load_profile, generate_persona
        existing = load_profile(profile_id)
        merged_facts = {**existing.get("facts", {}), **new_facts}
        data = generate_persona(profile_id=profile_id, facts=merged_facts)
        style = data.get("style", {})
        return {
            "updated":       True,
            "facts":         merged_facts,
            "style_summary": style.get("character_sketch", ""),
        }
    except Exception as exc:
        return {"error": str(exc), "updated": False}



@mcp.tool()
def humanize_prose(
    text: str,
    context: str,
    profile_id: str,
) -> dict:
    """
    Rewrite any text (CV summary, cover letter, free-text field) in the profile's voice.

    Args:
        text:       The text to rewrite.
        context:    What this text is for — "CV summary", "cover letter intro",
                    "assessment free text about teamwork", etc. Helps the LLM
                    calibrate tone appropriately.
        profile_id: Which profile's voice to use.

    Returns:
        {text: str, profile_id: str}
    """
    try:
        from answer_mcp._persona import get_persona_prompt, has_persona
        from answer_mcp._humanize import humanize_prose as _hp

        if not has_persona(profile_id):
            return {
                "error": f"No persona for profile '{profile_id}'. Assign one first.",
                "text": text,
            }

        persona_prompt = get_persona_prompt(profile_id)
        result = _hp(text=text, context=context,
                     persona_prompt=persona_prompt, profile_id=profile_id)
        return {"text": result, "profile_id": profile_id}
    except Exception as exc:
        return {"error": str(exc), "text": text}


if __name__ == "__main__":
    mcp.run()
