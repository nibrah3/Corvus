"""
check_pending_approvals.py — UserPromptSubmit hook.

Checks corvus:pending_approvals in Redis (via localhost:6380 SSH tunnel).
If jobs are waiting, injects a reminder into the prompt context so Claude
presents AskUserQuestion before doing other work.

Exit codes (Claude Code hook protocol):
  0  — proceed normally (no injection or injection added)
  2  — block and surface the message to the user (not used here)
"""
import json
import socket
import sys

REDIS_HOST = "127.0.0.1"
REDIS_PORT = 6380
KEY = "corvus:pending_approvals"


def redis_llen(key: str) -> int:
    try:
        with socket.create_connection((REDIS_HOST, REDIS_PORT), timeout=2) as sock:
            cmd = f"*2\r\n$4\r\nLLEN\r\n${len(key)}\r\n{key}\r\n"
            sock.sendall(cmd.encode())
            reply = sock.recv(256).decode().strip()
            # RESP integer reply: :N
            if reply.startswith(":"):
                return int(reply[1:])
    except Exception:
        pass
    return 0


def main():
    count = redis_llen(KEY)
    if count > 0:
        msg = (
            f"SYSTEM REMINDER: There are {count} job(s) waiting for approval in corvus:pending_approvals. "
            f"Before doing anything else, call mcp__vps__get_pending_approvals and present each job "
            f"to Mike using AskUserQuestion with options: [Apply] [Skip] [More Info]."
        )
        # Inject into the prompt context by writing to stdout (Claude Code hook injection protocol)
        print(json.dumps({"type": "system", "content": msg}))
    sys.exit(0)


if __name__ == "__main__":
    main()
