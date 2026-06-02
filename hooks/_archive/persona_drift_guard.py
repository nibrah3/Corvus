"""
persona_drift_guard.py — PostToolUse hook for mcp__answer__humanize_prose.
Reads the active persona's key facts and checks the generated answer for
obvious contradictions. Injects a SYSTEM REMINDER if a mismatch is found.
"""
import json
import re
import sys
from pathlib import Path

PROFILES_DIR = Path(__file__).parent.parent / "profiles"
STATE_FILE   = Path(__file__).parent.parent / ".approval_state.json"


def _load_profile(profile_id: str) -> dict:
    try:
        return json.loads((PROFILES_DIR / f"{profile_id}.json").read_text(encoding="utf-8"))
    except Exception:
        return {}


def _current_profile_id() -> str:
    try:
        return json.loads(STATE_FILE.read_text()).get("profile_id", "")
    except Exception:
        return ""


def _extract_answer(resp: dict) -> str:
    for key in ("text", "humanized", "result", "output", "content"):
        val = resp.get(key, "")
        if isinstance(val, str) and len(val) > 20:
            return val
    return ""


def main():
    try:
        ctx = json.loads(sys.stdin.read() or "{}")
    except Exception:
        sys.exit(0)

    answer = _extract_answer(ctx.get("tool_response", {}))
    if not answer:
        sys.exit(0)

    profile_id = _current_profile_id()
    if not profile_id:
        sys.exit(0)

    profile = _load_profile(profile_id)
    if not profile:
        sys.exit(0)

    facts  = profile.get("facts", {})
    lower  = answer.lower()
    issues = []

    # Name check
    name = profile.get("name") or facts.get("name", "")
    if name:
        first = name.split()[0].lower()
        m = re.search(r"(?:my name is|i am|i'm|this is)\s+([a-z]+)", lower)
        if m and m.group(1) != first:
            issues.append(f"Name: persona='{name}' but answer says '{m.group(1)}'")

    # Experience years check
    exp = facts.get("years_experience") or facts.get("experience_years")
    if exp:
        m = re.search(r"(\d+)\s+years?\s+(?:of\s+)?experience", lower)
        if m and abs(int(m.group(1)) - int(exp)) > 2:
            issues.append(f"Experience: persona={exp}yr but answer says {m.group(1)}yr")

    # Location check
    location = facts.get("location") or profile.get("location", "")
    if location:
        city = location.split(",")[0].strip().lower()
        if city and len(city) > 3:
            # If answer explicitly states a different city
            m = re.search(r"(?:based in|located in|living in|from)\s+([a-z\s]+?)(?:\.|,|$)", lower)
            if m and city not in m.group(1).lower():
                issues.append(f"Location: persona='{location}' but answer mentions '{m.group(1).strip()}'")

    if issues:
        print(json.dumps({
            "type": "system",
            "content": (
                "SYSTEM REMINDER: Persona drift detected in generated answer.\n"
                "Issues found:\n" +
                "\n".join(f"  • {i}" for i in issues) +
                "\n\nDo NOT type this answer. Regenerate with correct persona facts."
            )
        }))

    sys.exit(0)


if __name__ == "__main__":
    main()
