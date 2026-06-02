"""
notify_scraper_result.py — PostToolUse hook for mcp__vps__trigger_discovery.

Sends Telegram summary after a discovery scrape completes.
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

    tool_input    = ctx.get("tool_input", {})
    tool_response = ctx.get("tool_response", {})
    source        = tool_input.get("source", "all")
    error         = tool_response.get("error")

    if error:
        telegram_notify(f"Discovery scrape ({source}) failed: {error}")
        return

    # Try to extract job count from response
    count = tool_response.get("count") or tool_response.get("total") or tool_response.get("saved")
    if count is not None:
        telegram_notify(f"Discovery ({source}): {count} jobs found.")
    else:
        telegram_notify(f"Discovery ({source}) complete.")


if __name__ == "__main__":
    main()
