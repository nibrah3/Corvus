"""
hook_block_js_clicks.py — PreToolUse hook on mcp__cdp__cdp_eval

Blocks any cdp_eval expression that contains synthetic JS click patterns.
These patterns produce isTrusted=false events and break the stealth contract.

Allowed: read-only eval (querySelector, getBoundingClientRect, innerText, etc.)
Blocked: el.click(), dispatchEvent(), form.submit(), HTMLElement.click

Claude Code will see the block message and must find an OS-level alternative
(cdp_click_js with getBoundingClientRect + humanized_click, or click_selector).
"""
import json
import re
import sys

# Patterns that indicate a synthetic JS interaction (not a read)
BLOCKED_PATTERNS = [
    # Synthetic click delivery — all produce isTrusted=false
    r"\.click\s*\(",
    r"\.submit\s*\(",
    r"HTMLElement\.prototype",
    # dispatchEvent only blocked when used with pointer/mouse/click events.
    # dispatchEvent(new Event('input')) and dispatchEvent(new Event('change'))
    # are ALLOWED — they are needed for React controlled inputs after CDP insertText.
    r"dispatchEvent\s*\(\s*new\s+MouseEvent",
    r"dispatchEvent\s*\(\s*new\s+PointerEvent",
    r"dispatchEvent\s*\(\s*new\s+ClickEvent",
    r"dispatchEvent\s*\(\s*new\s+KeyboardEvent",
    # Standalone new MouseEvent/PointerEvent construction (used to fire synthetic clicks)
    r"new\s+MouseEvent\s*\(",
    r"new\s+PointerEvent\s*\(",
]

_BLOCK_RE = re.compile("|".join(BLOCKED_PATTERNS), re.IGNORECASE)


def main():
    try:
        # utf-8-sig strips the BOM that Windows PowerShell/Claude Code may prepend
        raw = sys.stdin.buffer.read().decode("utf-8-sig", errors="replace")
        data = json.loads(raw)
    except Exception:
        sys.exit(0)  # can't parse — let it through, don't break on bad input

    tool_input = data.get("tool_input") or {}
    expression = tool_input.get("expression") or ""

    if _BLOCK_RE.search(expression):
        # Exit code 2 = block with message shown to Claude
        print(
            "BLOCKED: cdp_eval contains a synthetic JS click pattern.\n"
            "Use CDPExecutor.click_js() or click_selector() instead — they resolve\n"
            "getBoundingClientRect() coords and deliver via pynput (OS HID).\n"
            f"Offending pattern in: {expression[:120]!r}",
            file=sys.stderr,
        )
        sys.exit(2)

    sys.exit(0)


if __name__ == "__main__":
    main()
