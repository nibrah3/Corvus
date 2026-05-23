"""
check_pending_approvals.py — UserPromptSubmit hook.

Checks corvus:pending_approvals in Redis (via localhost:6380 SSH tunnel).
If jobs are waiting, injects a reminder so Claude Code presents them via AskUserQuestion.

Exit codes (Claude Code hook protocol):
  0  — proceed normally
  2  — block (not used here)
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
            if reply.startswith(":"):
                return int(reply[1:])
    except Exception:
        pass
    return 0


def ix_running() -> bool:
    try:
        with socket.create_connection(("127.0.0.1", 53200), timeout=1):
            return True
    except Exception:
        return False


def main():
    hostname  = socket.gethostname()
    ix_status = "running" if ix_running() else "NOT running"
    count     = redis_llen(KEY)

    if count > 0:
        msg = (
            f"SYSTEM REMINDER: {count} job(s) waiting for approval. "
            f"Machine: {hostname} | IXBrowser: {ix_status}. "
            f"Before doing anything else, call mcp__vps__get_pending_approvals "
            f"and present each job via AskUserQuestion with options: "
            f"[Apply] [Skip] [More Info]. "
            f"If IXBrowser is not running, include [Launch IXBrowser] as an option — "
            f"run `python E:\\cb-core\\scripts\\check_ixbrowser.py --launch` to start it."
        )
        print(json.dumps({"type": "system", "content": msg}))

    sys.exit(0)


if __name__ == "__main__":
    main()
