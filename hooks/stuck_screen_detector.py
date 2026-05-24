"""
stuck_screen_detector.py — PostToolUse hook for mcp__capture__screenshot.
Hashes each screenshot. If the same screen appears 3+ consecutive times,
injects a SYSTEM REMINDER that the page may be stuck.
"""
import hashlib
import json
import os
import sys
from pathlib import Path

STATE_FILE      = Path(__file__).parent.parent / ".screen_state.json"
STUCK_THRESHOLD = 3


def _hash_image(path: str) -> str:
    try:
        with open(path, "rb") as f:
            return hashlib.md5(f.read()).hexdigest()
    except Exception:
        return ""


def _load() -> dict:
    try:
        return json.loads(STATE_FILE.read_text())
    except Exception:
        return {"last_hash": "", "count": 0}


def _save(state: dict) -> None:
    try:
        STATE_FILE.write_text(json.dumps(state))
    except Exception:
        pass


def main():
    try:
        ctx = json.loads(sys.stdin.read() or "{}")
    except Exception:
        sys.exit(0)

    resp = ctx.get("tool_response", {})
    path = (
        resp.get("image_path") or resp.get("path") or
        resp.get("file") or resp.get("screenshot_path") or ""
    )

    if not path or not os.path.exists(path):
        sys.exit(0)

    h     = _hash_image(path)
    state = _load()

    if h and h == state.get("last_hash"):
        state["count"] = state.get("count", 0) + 1
    else:
        state = {"last_hash": h, "count": 1}

    _save(state)

    if state["count"] >= STUCK_THRESHOLD:
        print(json.dumps({
            "type": "system",
            "content": (
                f"SYSTEM REMINDER: Screen unchanged across {state['count']} consecutive screenshots. "
                "Possible stuck state. Consider:\n"
                "  • Scroll down — there may be more content below\n"
                "  • Check for a hidden modal, popup, or loading overlay\n"
                "  • Look for a 'Next' button that requires scrolling to\n"
                "  • Reload the page if truly frozen\n"
                "  • Send screenshot to Telegram for manual review"
            )
        }))

    sys.exit(0)


if __name__ == "__main__":
    main()
