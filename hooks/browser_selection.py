"""
browser_selection.py — PreToolUse hook for mcp__browser__navigate.
Fires only on the first navigation of a session. Scans available browsers
and injects a SYSTEM REMINDER to present AskUserQuestion for profile selection.
State is written to .browser_selection_state.json to suppress on subsequent calls.
"""
import json
import os
import socket
import sys
from pathlib import Path

STATE_FILE = Path(__file__).parent.parent / ".browser_selection_state.json"


def _already_selected() -> bool:
    try:
        return json.loads(STATE_FILE.read_text()).get("selected", False)
    except Exception:
        return False


def _ix_running() -> bool:
    try:
        with socket.create_connection(("127.0.0.1", 53200), timeout=1):
            return True
    except Exception:
        return False


def _ix_profiles() -> list[str]:
    """Try to list IXBrowser profiles via local API."""
    try:
        import urllib.request
        req = urllib.request.Request(
            "http://127.0.0.1:53200/api/v2/profile/list",
            headers={"Content-Type": "application/json"}
        )
        with urllib.request.urlopen(req, timeout=3) as r:
            data = json.loads(r.read())
            profiles = data.get("data", []) or data.get("profiles", [])
            return [p.get("name", str(p.get("profile_id", "?"))) for p in profiles[:6]]
    except Exception:
        return []


def _chrome_profiles() -> list[str]:
    base = Path(os.environ.get("LOCALAPPDATA", "")) / "Google" / "Chrome" / "User Data"
    if not base.exists():
        return []
    found = []
    for p in base.iterdir():
        if p.is_dir() and (p.name == "Default" or p.name.startswith("Profile ")):
            if (p / "Preferences").exists():
                found.append(p.name)
    return found[:4]


def main():
    if _already_selected():
        sys.exit(0)

    options = []

    if _ix_running():
        ix_profiles = _ix_profiles()
        if ix_profiles:
            for name in ix_profiles:
                options.append(f"IXBrowser — profile: {name}")
        else:
            options.append("IXBrowser (running — no profiles listed via API)")

    for prof in _chrome_profiles():
        options.append(f"Chrome — {prof}")

    if not options:
        options.append("Chrome — Default (only browser detected)")

    lines = [
        "SYSTEM REMINDER: First browser navigation of this session.",
        "Before navigating, call AskUserQuestion to confirm which browser/profile to use.",
        "Detected options:",
    ] + [f"  • {o}" for o in options] + [
        "",
        "After user selects, write to .browser_selection_state.json: "
        '{"selected": true, "browser": "<choice>", "profile": "<profile_id>"}',
        "Then proceed with the navigation.",
    ]

    print(json.dumps({"type": "system", "content": "\n".join(lines)}))
    sys.exit(0)


if __name__ == "__main__":
    main()
