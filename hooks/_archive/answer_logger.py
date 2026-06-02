"""
answer_logger.py — PostToolUse hook for mcp__humanizer__humanized_type.
Logs every substantial typed answer to logs/answers.jsonl for future reference.
Builds a reusable answer history across assessment sessions.
"""
import json
import sys
import time
from pathlib import Path

LOG_FILE   = Path(__file__).parent.parent / "logs" / "answers.jsonl"
STATE_FILE = Path(__file__).parent.parent / ".approval_state.json"
MIN_LENGTH = 30


def _state() -> dict:
    try:
        return json.loads(STATE_FILE.read_text())
    except Exception:
        return {}


def main():
    try:
        ctx = json.loads(sys.stdin.read() or "{}")
    except Exception:
        sys.exit(0)

    tool_input = ctx.get("tool_input", {})
    text = (tool_input.get("text") or tool_input.get("keys") or "").strip()

    if len(text) < MIN_LENGTH:
        sys.exit(0)

    state = _state()
    entry = {
        "ts":         time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "job_id":     state.get("current_job_id"),
        "profile_id": state.get("profile_id"),
        "chars":      len(text),
        "text":       text[:2000],
    }

    try:
        LOG_FILE.parent.mkdir(parents=True, exist_ok=True)
        with open(LOG_FILE, "a", encoding="utf-8") as f:
            f.write(json.dumps(entry) + "\n")
    except Exception:
        pass

    sys.exit(0)


if __name__ == "__main__":
    main()
