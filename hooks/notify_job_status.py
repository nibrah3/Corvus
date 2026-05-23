"""
notify_job_status.py — PostToolUse hook for mcp__vps__update_job_status.

Sends Telegram for terminal statuses: applied, failed, skipped.
Silent for intermediate statuses like 'in_progress'.
"""
import json
import sys
import urllib.request

NOTIFY_STATUSES = {"applied", "failed", "error", "submitted", "skipped"}

EMOJI = {
    "applied":   "✅",
    "submitted": "✅",
    "failed":    "❌",
    "error":     "❌",
    "skipped":   "⏭",
}


def telegram_notify(text: str) -> None:
    try:
        payload = json.dumps({
            "jsonrpc": "2.0", "id": 1, "method": "tools/call",
            "params": {"name": "notify", "arguments": {"text": text}}
        }).encode()
        req = urllib.request.Request(
            "http://localhost:8706/mcp", data=payload,
            headers={"Content-Type": "application/json"}
        )
        urllib.request.urlopen(req, timeout=5)
    except Exception:
        pass


def main():
    try:
        ctx = json.loads(sys.stdin.read() or "{}")
    except Exception:
        ctx = {}

    tool_input    = ctx.get("tool_input", {})
    tool_response = ctx.get("tool_response", {})
    job_id = tool_input.get("job_id", "?")
    status = tool_input.get("status", "")
    result = tool_input.get("result", "")

    if status.lower() in NOTIFY_STATUSES:
        icon = EMOJI.get(status.lower(), "•")
        msg = f"{icon} Job #{job_id} → {status}"
        if result:
            msg += f"\n{result[:200]}"
        telegram_notify(msg)


if __name__ == "__main__":
    main()
