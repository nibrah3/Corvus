"""
PostToolCall hook — watches every mcp__* tool result for failures.
Sends a plain Telegram alert + restart instructions when one is detected.
Receives JSON via stdin: {tool_name, tool_input, tool_response}
"""
from __future__ import annotations
import json, os, sys, requests

RESTART_GUIDE = {
    "humanizer": "Restart: open a terminal in E:\\cb-core and run:  python -m humanizer_mcp.server",
    "capture":   "Restart: open a terminal in E:\\cb-core and run:  python -m capture_mcp.server",
    "uia":       "Restart: open a terminal in E:\\cb-core and run:  python -m uia_mcp.server",
    "browser":   "Restart: open a terminal in E:\\cb-core and run:  python -m browser_mcp.server",
    "gemini":    "Restart: open a terminal in E:\\cb-core and run:  python -m gemini_mcp.server",
    "telegram":  "Restart: open a terminal in E:\\cb-core and run:  python -m telegram_mcp.server",
    "answer":    "Restart: open a terminal in E:\\cb-core and run:  python -m answer_mcp.server",
    "sqlite":    "Restart: open a terminal in E:\\cb-core and run:  python -m mcp_server_sqlite --db-path E:/cb-core/careerbridge.db",
    "memory":    "Restart: open a terminal and run:  node C:\\Users\\Mike\\AppData\\Roaming\\npm\\node_modules\\@modelcontextprotocol\\server-memory\\dist\\index.js",
}


def _is_error(response) -> tuple[bool, str]:
    if isinstance(response, dict):
        if response.get("isError") or response.get("ok") is False:
            content = response.get("content", [])
            if isinstance(content, list) and content:
                text = content[0].get("text", str(response))
            else:
                text = response.get("error", str(response))
            return True, text[:300]
    if isinstance(response, str) and '"isError": true' in response:
        return True, response[:300]
    return False, ""


def _send(text: str):
    token = os.environ.get("TELEGRAM_BOT_TOKEN", "")
    chat_id = os.environ.get("TELEGRAM_ADMIN_CHAT_ID", "7994812711")
    if not token:
        return
    try:
        requests.post(
            f"https://api.telegram.org/bot{token}/sendMessage",
            json={"chat_id": int(chat_id), "text": text, "parse_mode": "HTML"},
            timeout=8,
        )
    except Exception:
        pass


def main():
    try:
        data = json.load(sys.stdin)
    except Exception:
        return

    tool_name: str = data.get("tool_name", "")
    response = data.get("tool_response", {})

    failed, reason = _is_error(response)
    if not failed:
        return

    # e.g. mcp__humanizer__humanize_prose → "humanizer"
    parts = tool_name.split("__")
    server = parts[1] if len(parts) >= 2 else tool_name
    guide = RESTART_GUIDE.get(server, f"Restart: reload the {server} MCP server in Claude Code settings.")

    msg = (
        f"⚠️ <b>{server}</b> stopped responding\n\n"
        f"<i>Error:</i> {reason}\n\n"
        f"<b>How to fix:</b>\n{guide}\n\n"
        f"After restarting, reload Claude Code (close and reopen) so it reconnects."
    )
    _send(msg)


if __name__ == "__main__":
    main()
