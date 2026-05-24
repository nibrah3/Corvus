"""
proxy_setup.py — PreToolUse hook for mcp__vps__upsert_profile.

Fires before a profile is created or updated. If the incoming profile data has
no proxy configured, injects a SYSTEM REMINDER asking Claude Code to present
an AskUserQuestion so the operator can supply proxy details (or confirm
no proxy is needed).

Exit codes:
  0 — proceed
  2 — block (used when a proxy field is required but missing and user hasn't confirmed)
"""
import json
import sys
from pathlib import Path

STATE_FILE = Path(__file__).parent.parent / ".approval_state.json"


def _state() -> dict:
    try:
        return json.loads(STATE_FILE.read_text(encoding="utf-8"))
    except Exception:
        return {}


def main() -> None:
    try:
        ctx = json.loads(sys.stdin.read() or "{}")
    except Exception:
        sys.exit(0)

    tool_input = ctx.get("tool_input", {})

    # Only intercept upsert_profile
    if ctx.get("tool_name") != "mcp__vps__upsert_profile":
        sys.exit(0)

    profile_data = tool_input.get("profile", tool_input)
    proxy = (
        profile_data.get("proxy")
        or profile_data.get("proxy_url")
        or profile_data.get("proxy_host")
        or ""
    )

    if proxy:
        # Proxy already specified — validate format and pass through
        if not (proxy.startswith("http://") or proxy.startswith("socks5://") or proxy.startswith("socks4://")):
            print(json.dumps({
                "type": "system",
                "content": (
                    "SYSTEM REMINDER: Proxy URL format looks wrong.\n"
                    f"  Got: {proxy!r}\n"
                    "  Expected: http://user:pass@host:port or socks5://host:port\n"
                    "Ask the user to confirm or correct the proxy before saving the profile."
                )
            }))
        sys.exit(0)

    # No proxy configured — ask operator to decide
    profile_name = profile_data.get("name") or profile_data.get("profile_id") or "this profile"
    print(json.dumps({
        "type": "system",
        "content": (
            f"SYSTEM REMINDER: Profile '{profile_name}' has no proxy configured.\n"
            "Present AskUserQuestion with options:\n"
            "  [No proxy — use direct connection]\n"
            "  [Enter proxy URL (http://user:pass@host:port)]\n"
            "  [Enter SOCKS5 proxy (socks5://host:port)]\n"
            "  [Cancel profile creation]\n\n"
            "If the user supplies a proxy URL, add it as 'proxy' field in the profile "
            "data and call mcp__vps__upsert_profile again with the updated payload. "
            "If 'No proxy', proceed without blocking."
        )
    }))

    # Do NOT block (exit 0) — Claude Code will present the gate before proceeding
    sys.exit(0)


if __name__ == "__main__":
    main()
