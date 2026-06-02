"""
browser_selection.py — PreToolUse hook for mcp__browser__navigate.

Fires on the first navigation of a session.

Auto-done:
  - Launches ixBrowser if not running.
  - Checks .defaults.json for a saved profile preference.
  - If a default profile is set: opens it silently (no user question).
  - If no default: fetches profile list and asks the user once, then saves
    their choice as the new default so it's never asked again.

The user never sees: ports, APIs, WebSocket, CDP, profile IDs, or tech details.
"""
import json
import os
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

STATE_FILE    = Path(__file__).parent.parent / ".browser_selection_state.json"
DEFAULTS_FILE = Path(__file__).parent.parent / ".defaults.json"
IX_EXE        = Path(r"C:\Program Files\ixBrowser\ixBrowser.exe")
IX_API        = "http://127.0.0.1:53200/api/v2"
IX_API_PORT   = 53200


def _already_selected() -> bool:
    try:
        return json.loads(STATE_FILE.read_text()).get("selected", False)
    except Exception:
        return False


def _defaults() -> dict:
    try:
        return json.loads(DEFAULTS_FILE.read_text(encoding="utf-8"))
    except Exception:
        return {}


def _ix_api_up() -> bool:
    import socket
    try:
        with socket.create_connection(("127.0.0.1", IX_API_PORT), timeout=1):
            return True
    except Exception:
        return False


def _launch_ix() -> bool:
    if not IX_EXE.exists():
        return False
    try:
        subprocess.Popen([str(IX_EXE)], creationflags=subprocess.DETACHED_PROCESS)
        return True
    except Exception:
        return False


def _ensure_ix_running() -> bool:
    if _ix_api_up():
        return True
    _launch_ix()
    for _ in range(24):
        time.sleep(0.5)
        if _ix_api_up():
            return True
    return False


def _ix_profiles() -> list[dict]:
    try:
        req = urllib.request.Request(
            f"{IX_API}/profile-list",
            data=b"{}",
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=5) as r:
            body = json.loads(r.read())
        profiles = (body.get("data") or {}).get("data") or []
        return [
            {"profile_id": p.get("profile_id"), "name": p.get("name", f"Profile {p.get('profile_id')}")}
            for p in profiles
        ]
    except Exception:
        return []


def _chrome_available() -> bool:
    base = Path(os.environ.get("LOCALAPPDATA", "")) / "Google" / "Chrome" / "User Data"
    return (base / "Default" / "Preferences").exists()


def main():
    if _already_selected():
        sys.exit(0)

    ix_up = _ensure_ix_running()
    defaults = _defaults()
    saved_profile_id = defaults.get("ixbrowser_profile_id")

    # --- Fast path: default already set — confirm or let user switch ---
    if saved_profile_id and ix_up:
        profiles = _ix_profiles()
        match = next((p for p in profiles if str(p["profile_id"]) == str(saved_profile_id)), None)
        profile_name = match["name"] if match else f"Profile {saved_profile_id}"
        all_profile_lines = [f"  • {p['name']} (id={p['profile_id']})" for p in profiles]
        if _chrome_available():
            all_profile_lines.append("  • Chrome — Default")
        defaults_path = str(DEFAULTS_FILE)
        print(json.dumps({
            "type": "system",
            "content": (
                f"SYSTEM REMINDER: Browser profile default is set to '{profile_name}'.\n\n"
                f"YOUR TASK:\n"
                f"  Present AskUserQuestion:\n"
                f"    question: 'Which browser profile should I use?'\n"
                f"    options:\n"
                f"      label: 'Use {profile_name}' — description: 'Continue with your saved default.'\n"
                f"      label: 'Choose another' — description: 'Pick a different profile for this session.'\n\n"
                f"  If user picks 'Use {profile_name}':\n"
                f"    1. POST {IX_API}/profile-open with {{\"profile_id\": \"{saved_profile_id}\"}}.\n"
                f"    2. Extract debug port from 'data.ws', call cdp_connect.\n"
                f"    3. Write to .browser_selection_state.json: "
                f'{{\"selected\": true, \"browser\": \"ixbrowser\", \"profile_id\": \"{saved_profile_id}\", \"profile_name\": \"{profile_name}\"}}.\n'
                f"    4. Proceed with navigation.\n\n"
                f"  If user picks 'Choose another':\n"
                f"    Present a second AskUserQuestion with ALL available profiles as buttons:\n"
                + "\n".join(f"    {line}" for line in all_profile_lines) + "\n"
                f"    Plus '+ Add new profile'.\n"
                f"    After user picks:\n"
                f"      a. Read {defaults_path}, update 'ixbrowser_profile_id' to the new choice, write back.\n"
                f"      b. Open the profile via ixBrowser API, connect CDP.\n"
                f"      c. Write .browser_selection_state.json, proceed with navigation.\n"
                f"  DO NOT mention: ports, APIs, profile IDs, or technical details."
            )
        }))
        sys.exit(0)

    # --- No default: ask user once ---
    profiles = _ix_profiles() if ix_up else []
    profile_lines = [f"  • {p['name']} (id={p['profile_id']})" for p in profiles]
    if _chrome_available():
        profile_lines.append("  • Chrome — Default")
    if not profile_lines:
        profile_lines.append("  • Chrome — Default (no ixBrowser profiles found)")

    defaults_path = str(DEFAULTS_FILE)

    lines = [
        "SYSTEM REMINDER: First browser session — choose a profile.",
        "",
        "YOUR TASK:",
        "  Present AskUserQuestion: 'Which profile would you like to use?'",
        "  Show ONLY profile names as buttons (no IDs, no ports, no tech terms).",
        "  Include '+ Add new profile' as the last option.",
        "  Each button description: 'Your choice will be saved as your default — you won't be asked again.'",
        "",
        "Available profiles:",
    ] + profile_lines + [
        "",
        "After the user picks:",
        "  1. Read .defaults.json, set 'ixbrowser_profile_id' to the chosen profile_id, write back.",
        "  2. POST to the ixBrowser API to open the profile.",
        "  3. Call cdp_connect with the returned debug port.",
        "  4. Write to .browser_selection_state.json: {\"selected\": true, \"browser\": \"ixbrowser\", \"profile_id\": <id>, \"profile_name\": \"<name>\"}",
        "  5. Proceed with navigation.",
        f"  Defaults file: {defaults_path}",
        "  DO NOT mention: ports, APIs, profile IDs, or any technical details to the user.",
    ]

    print(json.dumps({"type": "system", "content": "\n".join(lines)}))
    sys.exit(0)


if __name__ == "__main__":
    main()
