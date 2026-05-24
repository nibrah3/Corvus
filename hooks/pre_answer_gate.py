"""
pre_answer_gate.py — PreToolUse hook for mcp__humanizer__humanized_type.
Before typing any substantial answer text during an assessment, injects a
SYSTEM REMINDER confirming the answer was reviewed via AskUserQuestion.
Safety net for cases where the approval flow was accidentally skipped.
Does NOT block — reminds and lets Claude verify.
"""
import json
import sys
import time
from pathlib import Path

STATE_FILE    = Path(__file__).parent.parent / ".approval_state.json"
GATE_LOG_FILE = Path(__file__).parent.parent / ".last_gate_response.json"
MIN_LENGTH    = 40    # characters — short strings are navigation, not answers
GATE_GRACE_S  = 90   # seconds — if a gate was approved this recently, skip the reminder


def _in_assessment() -> bool:
    try:
        state = json.loads(STATE_FILE.read_text())
        return bool(state.get("current_job_id"))
    except Exception:
        return False


def _recently_gate_approved() -> bool:
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

    # Only gate substantial text
    if len(text) < MIN_LENGTH:
        sys.exit(0)

    # Only gate during an active assessment
    if not _in_assessment():
        sys.exit(0)

    # Skip if a gate was recently approved (answer was already reviewed)
    if _recently_gate_approved():
        sys.exit(0)

    preview = text[:150].replace("\n", " ")

    print(json.dumps({
        "type": "system",
        "content": (
            f"SYSTEM REMINDER: About to type a {len(text)}-character answer:\n"
            f"  \"{preview}{'...' if len(text) > 150 else ''}\"\n\n"
            "Verify this answer was reviewed via AskUserQuestion "
            "[✅ Approve] [✏️ Edit] [🔄 Regenerate] BEFORE typing.\n"
            "If not yet reviewed — STOP and present it for approval first.\n"
            "After approval, write {\"ts\": <timestamp>} to .last_gate_response.json to clear this reminder."
        )
    }))
    sys.exit(0)


if __name__ == "__main__":
    main()
