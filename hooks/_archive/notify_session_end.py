"""
notify_session_end.py — Stop hook.

Sends a brief Telegram summary when the Claude Code session ends:
- pending jobs remaining
- jobs approved this session
- any active task
"""
import json
import socket
import sys
import urllib.request

REDIS_HOST = "127.0.0.1"
REDIS_PORT = 6380


def _redis_llen(key: str) -> int:
    try:
        with socket.create_connection((REDIS_HOST, REDIS_PORT), timeout=2) as sock:
            cmd = f"*2\r\n$4\r\nLLEN\r\n${len(key)}\r\n{key}\r\n"
            sock.sendall(cmd.encode())
            reply = sock.recv(256).decode().strip()
            if reply.startswith(":"):
                return int(reply[1:])
    except Exception:
        pass
    return -1


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

    stop_reason = ctx.get("stop_reason", "")
    if stop_reason == "error":
        return  # Don't spam on errors

    pending  = _redis_llen("corvus:pending_approvals")
    approved = _redis_llen("corvus:approved_jobs")

    parts = ["Session ended."]
    if pending > 0:
        parts.append(f"{pending} jobs still pending approval.")
    if approved > 0:
        parts.append(f"{approved} jobs in application queue.")
    if pending == 0 and approved == 0:
        parts.append("Queue clear.")

    telegram_notify(" ".join(parts))


if __name__ == "__main__":
    main()
