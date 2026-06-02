"""
assessment_tab_selection.py — PostToolUse hook for mcp__vps__approve_job.

Fires after a job is approved, before the assessment begins.
Checks what tabs are currently open in the browser and asks the user
to either select one or provide a URL.

What the user sees:
  - A list of open tab titles (if any look like assessments) OR
  - "Paste the assessment link" if no tabs are open or tabs look wrong.
Never shows: CDP, WebSocket, port numbers, tab IDs, or technical details.
"""
import json
import sys
import urllib.request
from pathlib import Path

STATE_FILE = Path(__file__).parent.parent / ".browser_selection_state.json"


def _browser_state() -> dict:
    try:
        return json.loads(STATE_FILE.read_text())
    except Exception:
        return {}


def _open_tabs(port: int) -> list[dict]:
    """Return list of {title, url} for open page tabs."""
    try:
        req = urllib.request.Request(
            f"http://127.0.0.1:{port}/json",
            headers={"User-Agent": "CareerBridge/1.0"},
        )
        with urllib.request.urlopen(req, timeout=3) as r:
            targets = json.loads(r.read())
        return [
            {"title": t.get("title", "Untitled"), "url": t.get("url", "")}
            for t in targets
            if t.get("type") == "page"
            and not t.get("url", "").startswith("chrome://")
        ]
    except Exception:
        return []


def _get_debug_port() -> int | None:
    """Try to find the currently open ixBrowser debug port from netstat."""
    try:
        import subprocess
        result = subprocess.run(
            ["netstat", "-ano"],
            capture_output=True, text=True, timeout=5
        )
        for line in result.stdout.splitlines():
            if "127.0.0.1:" in line and "LISTEN" in line:
                port_str = line.split()[1].split(":")[-1]
                port = int(port_str)
                if 10000 < port < 60000:
                    # Try it as a CDP port
                    req = urllib.request.Request(
                        f"http://127.0.0.1:{port}/json/version",
                        headers={"User-Agent": "CareerBridge/1.0"},
                    )
                    with urllib.request.urlopen(req, timeout=1) as r:
                        data = json.loads(r.read())
                    if "webSocketDebuggerUrl" in data:
                        return port
    except Exception:
        pass
    return None


def main() -> None:
    try:
        ctx = json.loads(sys.stdin.read() or "{}")
    except Exception:
        sys.exit(0)

    tool_name = ctx.get("tool_name", "")
    if tool_name != "mcp__vps__approve_job":
        sys.exit(0)

    # Find open tabs
    state = _browser_state()
    debug_port = _get_debug_port()
    tabs = _open_tabs(debug_port) if debug_port else []

    # Build tab options for the reminder
    if tabs:
        tab_lines = [f"  • \"{t['title']}\" ({t['url'][:60]})" for t in tabs[:5]]
        tab_section = (
            "Open browser tabs detected:\n"
            + "\n".join(tab_lines)
            + "\n\nYOUR TASK:\n"
            "  Present AskUserQuestion:\n"
            "    Question: 'Which tab has the assessment?'\n"
            "    Buttons: one button per tab title (show only the page title, NOT the URL)\n"
            "             + 'Paste a different link'\n"
            "  After user picks a tab: navigate CDP to that URL and begin.\n"
            "  After user picks 'Paste a link': ask for the URL via AskUserQuestion free text."
        )
    else:
        tab_section = (
            "No assessment tabs detected in the browser.\n\n"
            "YOUR TASK:\n"
            "  Present AskUserQuestion:\n"
            "    Question: 'What's the assessment link?'\n"
            "    Options: 'I'll paste it' (then ask for input), 'It's already open — check again'\n"
            "  DO NOT mention: ports, CDP, WebSocket, or any technical details."
        )

    print(json.dumps({
        "type": "system",
        "content": (
            "SYSTEM REMINDER: Job approved — assessment URL needed before starting.\n\n"
            + tab_section
        )
    }))
    sys.exit(0)


if __name__ == "__main__":
    main()
