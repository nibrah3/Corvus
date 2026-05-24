"""
profile_selection.py — PreToolUse hook for mcp__vps__get_profile and assessment start.

Fires the first time an assessment session begins (detected by absence of a
current_job_id in .approval_state.json). Lists available profiles from the VPS
and injects a SYSTEM REMINDER asking Claude Code to present an AskUserQuestion
so the operator picks which persona to use (or creates a new one).

Exit codes:
  0 — proceed (or profile already selected)
  2 — block (should not happen — we let Claude handle the UI gate)
"""
import json
import socket
import sys
from pathlib import Path

STATE_FILE = Path(__file__).parent.parent / ".approval_state.json"
FLAG_FILE  = Path(__file__).parent.parent / ".profile_selection_done.json"

VPS_MCP_PORT = 8713   # vps_mcp listens here


def _state() -> dict:
    try:
        return json.loads(STATE_FILE.read_text(encoding="utf-8"))
    except Exception:
        return {}


def _flag_active() -> bool:
    """Return True if a profile was already selected in this session."""
    try:
        data = json.loads(FLAG_FILE.read_text(encoding="utf-8"))
        # Flag is valid if profile_id matches current state
        state = _state()
        return data.get("profile_id") == state.get("profile_id") and bool(data.get("profile_id"))
    except Exception:
        return False


def _vps_mcp_up() -> bool:
    try:
        with socket.create_connection(("127.0.0.1", VPS_MCP_PORT), timeout=1):
            return True
    except Exception:
        return False


def main() -> None:
    try:
        ctx = json.loads(sys.stdin.read() or "{}")
    except Exception:
        sys.exit(0)

    # Only fires when starting an assessment (job being set for the first time)
    tool_name = ctx.get("tool_name", "")
    tool_input = ctx.get("tool_input", {})

    # Trigger on approve_job (assessment about to begin) or explicit get_profile call
    if tool_name not in ("mcp__vps__approve_job", "mcp__vps__get_profile"):
        sys.exit(0)

    # If a profile is already selected for this session, skip
    if _flag_active():
        sys.exit(0)

    state = _state()
    current_profile = state.get("profile_id", "")

    if _vps_mcp_up():
        profile_hint = (
            "Call mcp__vps__list_profiles to get available profiles, then present them via "
            "AskUserQuestion with options for each profile name plus [+ Create New Profile]. "
            "After the user selects, call mcp__vps__get_profile with the chosen ID and store "
            f"profile_id in .approval_state.json. Then write the selected profile_id to "
            f"{FLAG_FILE} as {{\"profile_id\": \"<selected_id>\"}} to skip this gate for the rest of the session."
        )
    else:
        profile_hint = (
            "vps_mcp is not running — cannot list profiles. "
            "Ask the user to type the profile ID manually."
        )

    current_note = f" Currently active: '{current_profile}'." if current_profile else " No profile active."

    print(json.dumps({
        "type": "system",
        "content": (
            f"SYSTEM REMINDER: Profile selection required before starting assessment.{current_note}\n"
            f"{profile_hint}"
        )
    }))

    sys.exit(0)


if __name__ == "__main__":
    main()
