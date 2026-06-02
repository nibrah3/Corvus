#!/usr/bin/env python3
"""
hook_present_profiles.py - PostToolUse hook (Module 5)
Fires after mcp__vps__list_profiles.
Formats profile list so Claude presents cards one at a time.
Never blocks -- always exits 0.
"""
import io
import json
import sys
from pathlib import Path

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

DEFAULTS_FILE  = Path(__file__).parent.parent / ".defaults.json"
PROXY_MAP_FILE = Path(__file__).parent.parent / "profiles" / ".proxy_map.json"


def _active_id() -> str:
    try:
        return json.loads(DEFAULTS_FILE.read_text(encoding="utf-8")).get("candidate_profile_id", "")
    except Exception:
        return ""


def _proxy_map() -> dict:
    try:
        return json.loads(PROXY_MAP_FILE.read_text(encoding="utf-8"))
    except Exception:
        return {}


def fmt_profile(idx: int, total: int, p: dict, active_id: str, proxy_map: dict) -> str:
    pid   = str(p.get("id") or p.get("profile_id") or "").strip()
    name  = (p.get("name") or "Unknown").strip()
    email = (p.get("email") or "").strip()

    active_tag = " [ACTIVE]" if pid and pid == active_id else ""
    proxy_str  = "Proxy: configured" if proxy_map.get(pid) else "Proxy: none"
    email_str  = email if email else "no email on file"

    return (
        f"{idx}/{total}. \"{name}\"{active_tag}\n"
        f"   {email_str}  |  {proxy_str}"
    )


def main():
    try:
        raw = sys.stdin.buffer.read().decode("utf-8-sig", errors="replace")
        ctx = json.loads(raw) if raw.strip() else {}
    except Exception:
        sys.exit(0)

    tool_response = ctx.get("tool_response", {})
    if isinstance(tool_response, str):
        try:
            tool_response = json.loads(tool_response)
        except Exception:
            tool_response = {}
    if not isinstance(tool_response, dict):
        tool_response = {}

    if "error" in tool_response:
        print(
            "[PROFILES ERROR]\n"
            f"Could not load profiles: {tool_response['error']}\n"
            "Tell the user warmly and show the My Setup sub-menu."
        )
        sys.exit(0)

    profiles = tool_response.get("profiles") or []
    if not isinstance(profiles, list):
        profiles = []

    if not profiles:
        print(
            "[PROFILES - NONE]\n"
            "No profiles found.\n"
            "Tell the user: \"You don't have any profiles set up yet - let's create one!\"\n"
            "Then immediately show the My Setup sub-menu.\n"
            "Highlight the Create Profile option in your message."
        )
        sys.exit(0)

    active_id  = _active_id()
    proxy_map  = _proxy_map()
    total      = len(profiles)
    lines      = [fmt_profile(i + 1, total, p, active_id, proxy_map) for i, p in enumerate(profiles)]

    output = (
        f"[PROFILES READY - {total} profile(s)]\n"
        "Present these profiles ONE AT A TIME as AskUserQuestion cards, starting with profile #1.\n\n"
        "Card format for each profile:\n"
        "  question: \"[Name]\"\n"
        "  header:   \"Profile [N] of [total]\"\n"
        "  options:\n"
        "    [Set as Active]        -> read D:\\cb-core\\.defaults.json, set 'candidate_profile_id'\n"
        "                             to this profile's id, write back. Say:\n"
        "                             \"Done! [Name] is now your active profile.\"\n"
        "                             Then show the My Setup sub-menu.\n"
        "    [Next Profile]         -> present the next profile card\n"
        "    [Back to My Setup]     -> show the My Setup sub-menu\n\n"
        "IMPORTANT: If the profile is marked [ACTIVE], change its button label to:\n"
        "  [Active - keep this one]  (same action: confirm and show My Setup sub-menu)\n"
        "After the last profile, show the My Setup sub-menu.\n"
        "Never show profile IDs, database field names, or technical internals.\n\n"
        "Profiles:\n" + "\n".join(lines)
    )

    print(output)
    sys.exit(0)


if __name__ == "__main__":
    main()
