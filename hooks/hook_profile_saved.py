#!/usr/bin/env python3
"""
hook_profile_saved.py - PostToolUse hook (Module 5)
Fires after mcp__vps__upsert_profile.
Confirms profile creation/update in plain English and shows My Setup sub-menu.
Never blocks -- always exits 0.
"""
import io
import json
import sys

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")


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
            "[PROFILE SAVE ERROR]\n"
            f"Error: {tool_response['error']}\n"
            "Tell the user: \"I had a little trouble saving that profile - give me a moment and I'll try again.\"\n"
            "Retry the upsert_profile call once. If it fails again, show the My Setup sub-menu."
        )
        sys.exit(0)

    profile_id = tool_response.get("profile_id", "")
    print(
        "[PROFILE SAVED]\n"
        f"profile_id={profile_id}\n"
        "Tell the user: \"Profile saved! They're all set and ready to go.\"\n"
        "Then show the My Setup sub-menu via AskUserQuestion."
    )
    sys.exit(0)


if __name__ == "__main__":
    main()
