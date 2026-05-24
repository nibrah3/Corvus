"""
pre_submit_gate.py — PreToolUse hook for mcp__humanizer__humanized_click.
If the target element looks like a submit/apply/send button, injects a
SYSTEM REMINDER requiring screenshot + AskUserQuestion confirmation first.
Does NOT block (exit 0) — it reminds and lets Claude decide.
"""
import json
import sys

SUBMIT_KEYWORDS = {
    "submit", "apply", "send", "confirm", "finish", "complete",
    "save and continue", "save & continue", "next step", "review and submit",
    "submit application", "apply now", "send application",
}

# Keywords that are safe to click without the gate
SAFE_KEYWORDS = {"next", "continue", "proceed", "save"}


def _target_label(tool_input: dict) -> str:
    for field in ("label", "element_description", "target", "text", "element_text", "description", "title"):
        val = (tool_input.get(field) or "").strip()
        if val:
            return val
    return ""


def _is_submit(label: str) -> bool:
    lower = label.lower()
    # Definite submit signals
    if any(kw in lower for kw in SUBMIT_KEYWORDS):
        return True
    # "next" / "continue" alone are not final submits — skip them
    return False


def main():
    try:
        ctx = json.loads(sys.stdin.read() or "{}")
    except Exception:
        sys.exit(0)

    tool_input = ctx.get("tool_input", {})
    label = _target_label(tool_input)

    if not label or not _is_submit(label):
        sys.exit(0)

    print(json.dumps({
        "type": "system",
        "content": (
            f"SYSTEM REMINDER: About to click a final submit/apply button: '{label[:80]}'.\n"
            "REQUIRED before proceeding:\n"
            "1. Call mcp__capture__screenshot() — confirm the full form is filled correctly.\n"
            "2. Call mcp__telegram__send_screenshot() — send to admin for visibility.\n"
            "3. AskUserQuestion: [✅ Confirm & Submit] [✏️ Review Form First] [🚫 Cancel].\n"
            "Only click after explicit user confirmation."
        )
    }))
    sys.exit(0)


if __name__ == "__main__":
    main()
