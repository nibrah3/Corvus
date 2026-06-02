"""
profile_selection.py — PreToolUse hook for mcp__vps__approve_job / get_profile.

Fires at the start of an assessment to ensure a candidate profile is chosen.

Auto-done:
  - Checks .defaults.json for a saved candidate_profile_id.
  - If a default is set: loads it silently (no user question).
  - If no default: lists candidate profiles and asks once, then saves the choice
    so it's never asked again.

The user sees: first name + last name buttons only.
Never shows: VPS, database, profile IDs, or any internal system names.
"""
import json
import socket
import sys
from pathlib import Path

STATE_FILE    = Path(__file__).parent.parent / ".approval_state.json"
FLAG_FILE     = Path(__file__).parent.parent / ".profile_selection_done.json"
DEFAULTS_FILE = Path(__file__).parent.parent / ".defaults.json"
VPS_PORT      = 8713


def _state() -> dict:
    try:
        return json.loads(STATE_FILE.read_text(encoding="utf-8"))
    except Exception:
        return {}


def _defaults() -> dict:
    try:
        return json.loads(DEFAULTS_FILE.read_text(encoding="utf-8"))
    except Exception:
        return {}


def _already_selected() -> bool:
    try:
        data = json.loads(FLAG_FILE.read_text(encoding="utf-8"))
        state = _state()
        return (
            bool(data.get("profile_id"))
            and data.get("profile_id") == state.get("profile_id")
        )
    except Exception:
        return False


def _vps_up() -> bool:
    try:
        with socket.create_connection(("127.0.0.1", VPS_PORT), timeout=1):
            return True
    except Exception:
        return False


def main() -> None:
    try:
        ctx = json.loads(sys.stdin.read() or "{}")
    except Exception:
        sys.exit(0)

    tool_name = ctx.get("tool_name", "")
    if tool_name not in ("mcp__vps__approve_job", "mcp__vps__get_profile"):
        sys.exit(0)

    if _already_selected():
        sys.exit(0)

    defaults = _defaults()
    saved_profile_id = defaults.get("candidate_profile_id")
    flag_path = str(FLAG_FILE)
    defaults_path = str(DEFAULTS_FILE)

    # --- Fast path: default already set — confirm or let user switch ---
    if saved_profile_id and _vps_up():
        print(json.dumps({
            "type": "system",
            "content": (
                f"SYSTEM REMINDER: Default candidate is set (ID: {saved_profile_id}).\n\n"
                f"YOUR TASK:\n"
                f"  1. Call mcp__vps__get_profile with profile_id='{saved_profile_id}' to get their name.\n"
                f"  2. Present AskUserQuestion:\n"
                f"       question: 'Which candidate should handle this application?'\n"
                f"       options:\n"
                f"         label: 'Use <first name> <last name>' (from the profile) "
                f"— description: 'Continue with your saved default.'\n"
                f"         label: 'Choose another' — description: 'Pick a different candidate.'\n\n"
                f"  If user picks the default candidate:\n"
                f"    a. Write {{\"profile_id\": \"{saved_profile_id}\"}} to {flag_path}.\n"
                f"    b. Proceed with the job approval.\n\n"
                f"  If user picks 'Choose another':\n"
                f"    a. Call mcp__vps__list_profiles.\n"
                f"    b. Present all candidates by first + last name as buttons, plus '+ Create new candidate'.\n"
                f"    c. After user picks:\n"
                f"       - Read {defaults_path}, update 'candidate_profile_id' to the new ID, write back.\n"
                f"       - Write {{\"profile_id\": \"<new_id>\"}} to {flag_path}.\n"
                f"       - Call mcp__vps__get_profile with the new ID.\n"
                f"       - Proceed with the job approval.\n"
                f"  DO NOT show: profile IDs, database fields, or system names."
            )
        }))
        sys.exit(0)

    # --- No default: ask user once ---
    if _vps_up():
        instructions = (
            "YOUR TASK:\n"
            "  1. Call mcp__vps__list_profiles to get candidate profiles.\n"
            "  2. Present AskUserQuestion: 'Which candidate should handle this application?'\n"
            "     Show ONLY first name + last name as button labels.\n"
            "     Each button description: 'Your choice will be saved as your default — you won't be asked again.'\n"
            "     Include a '+ Create new candidate' button at the end.\n"
            "  3. After user picks:\n"
            f"     a. Read {defaults_path}, set 'candidate_profile_id' to the chosen profile ID, write back.\n"
            f"     b. Write {{\"profile_id\": \"<id>\"}} to {flag_path}.\n"
            "     c. Call mcp__vps__get_profile with the chosen ID.\n"
            "     d. Proceed with the job approval.\n"
            "  DO NOT show: profile IDs, database fields, or system names."
        )
    else:
        instructions = (
            "Candidate management is temporarily unavailable.\n"
            "Ask the user: 'Which candidate should handle this? (type a name)'\n"
            "Use their answer to find the right profile manually."
        )

    print(json.dumps({
        "type": "system",
        "content": (
            "SYSTEM REMINDER: Candidate profile selection needed.\n\n"
            + instructions
        )
    }))
    sys.exit(0)


if __name__ == "__main__":
    main()
