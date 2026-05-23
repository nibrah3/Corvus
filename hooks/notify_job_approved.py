"""
notify_job_approved.py — PostToolUse hook for mcp__vps__approve_job.

Sends a Telegram notification when a job is approved and queued for application.
"""
import json
import sys
import urllib.request


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

    tool_response = ctx.get("tool_response", {})
    tool_input    = ctx.get("tool_input", {})
    job_id        = tool_input.get("job_id") or tool_response.get("job_id", "?")
    ok            = tool_response.get("ok") or not tool_response.get("error")

    if ok:
        telegram_notify(f"Job #{job_id} approved. Queued for application.")
    else:
        err = tool_response.get("error", "unknown error")
        telegram_notify(f"Job #{job_id} approval failed: {err}")


if __name__ == "__main__":
    main()
