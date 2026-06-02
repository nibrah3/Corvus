"""
pre_answer_gate.py — PreToolUse hook for mcp__humanizer__humanized_type.

Before typing any substantial answer into a form, injects a SYSTEM REMINDER
telling Claude Code to show the user what it's about to type and get approval.

What the user sees: the drafted answer + [Send it] [Edit] [Skip] buttons.
Never shows: tool names, selectors, JS, or any technical details.
"""
import json
import sys
import time
from pathlib import Path

STATE_FILE    = Path(__file__).parent.parent / ".approval_state.json"
GATE_LOG_FILE = Path(__file__).parent.parent / ".last_gate_response.json"
MIN_LENGTH    = 40      # characters — short strings are navigation clicks, not answers
GATE_GRACE_S  = 90     # seconds — if approved this recently, skip the reminder


def _in_assessment() -> bool:
    try:
        return bool(json.loads(STATE_FILE.read_text()).get("current_job_id"))
    except Exception:
        return False


def _recently_approved() -> bool:
    try:
        data = json.loads(GATE_LOG_FILE.read_text())
        return (time.time() - float(data.get("ts", 0))) < GATE_GRACE_S
    except Exception:
        return False


def main():
    try:
        ctx = json.loads(sys.stdin.read() or "{}")
    except Exception:
        sys.exit(0)

    tool_input = ctx.get("tool_input", {})
    text = (tool_input.get("text") or tool_input.get("keys") or "").strip()

    if len(text) < MIN_LENGTH:
        sys.exit(0)

    if not _in_assessment():
        sys.exit(0)

    if _recently_approved():
        sys.exit(0)

    preview = text[:200].replace("\n", " ")
    ellipsis = "…" if len(text) > 200 else ""

    print(json.dumps({
        "type": "system",
        "content": (
            "SYSTEM REMINDER: About to submit an answer — USER APPROVAL REQUIRED.\n\n"
            f"Planned response ({len(text)} characters):\n"
            f"  \"{preview}{ellipsis}\"\n\n"
            "YOUR TASK:\n"
            "  1. Present AskUserQuestion to the user:\n"
            "       Question: 'Here's the answer I'll submit — does it look good?'\n"
            "       Show the full answer text in the description of the first option.\n"
            "       Buttons: [Send it] [Let me edit it] [Skip this question]\n"
            "  2. On 'Send it': write {\"ts\": <timestamp>} to .last_gate_response.json, then type.\n"
            "  3. On 'Let me edit it': show the draft for editing, re-present for approval.\n"
            "  4. On 'Skip': do NOT type anything. Move to the next question.\n"
            "  DO NOT mention: field selectors, JS, tool names, or any system internals."
        )
    }))
    sys.exit(0)


if __name__ == "__main__":
    main()
