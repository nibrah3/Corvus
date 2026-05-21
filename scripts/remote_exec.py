"""
remote_exec.py — Send a command to DESKTOP-5OP0RFK via VPS tunnel.

Usage (from Python):
    from scripts.remote_exec import remote_exec
    result = remote_exec("Get-Process | Select-Object -First 5 | Format-Table Name,CPU")
    print(result["stdout"])

Usage (CLI):
    python -m scripts.remote_exec "Get-ChildItem D:\\cb-core"
    python -m scripts.remote_exec "import sys; print(sys.version)" --shell python

Requires:
    - DESKTOP-5OP0RFK is running start_remote_agent.ps1 (reverse tunnel active)
    - SSH access to root@77.42.91.185 from this machine
"""
from __future__ import annotations

import json
import subprocess
import sys

VPS        = "root@77.42.91.185"
PORT       = 7071
AUTH_TOKEN = "cb-remote-2026-xk9"


def remote_exec(cmd: str, shell: str = "powershell", timeout: int = 130) -> dict:
    """Run cmd on DESKTOP-5OP0RFK. Returns {stdout, stderr, returncode}."""
    payload = json.dumps({"cmd": cmd, "shell": shell})
    # Route through VPS — the reverse tunnel makes localhost:7070 on VPS
    # point to the remote agent running on DESKTOP-5OP0RFK.
    ssh_cmd = [
        "ssh",
        "-o", "StrictHostKeyChecking=no",
        "-o", "ConnectTimeout=10",
        VPS,
        (
            f"curl -sf -X POST"
            f" -H 'X-Auth: {AUTH_TOKEN}'"
            f" -H 'Content-Type: application/json'"
            f" -d '{payload.replace(chr(39), chr(39)+chr(92)+chr(39)+chr(39))}'"
            f" http://localhost:{PORT}"
        ),
    ]
    r = subprocess.run(ssh_cmd, capture_output=True, text=True, timeout=timeout)
    if r.returncode != 0:
        raise ConnectionError(f"VPS relay failed (exit {r.returncode}): {r.stderr.strip()}")
    return json.loads(r.stdout)


def remote_ping() -> bool:
    """Return True if the remote agent is reachable."""
    try:
        r = subprocess.run(
            ["ssh", "-o", "StrictHostKeyChecking=no", "-o", "ConnectTimeout=5",
             VPS, f"curl -sf http://localhost:{PORT}/ping"],
            capture_output=True, text=True, timeout=15,
        )
        return r.returncode == 0 and r.stdout.strip() == "pong"
    except Exception:
        return False


if __name__ == "__main__":
    import argparse
    p = argparse.ArgumentParser()
    p.add_argument("cmd", help="Command to run on remote machine")
    p.add_argument("--shell", default="powershell", choices=["powershell", "python", "cmd"])
    p.add_argument("--ping", action="store_true", help="Just ping the remote agent")
    args = p.parse_args()

    if args.ping:
        ok = remote_ping()
        print("Remote agent: OK" if ok else "Remote agent: NOT REACHABLE")
        sys.exit(0 if ok else 1)

    result = remote_exec(args.cmd, shell=args.shell)
    if result["stdout"]:
        print(result["stdout"], end="")
    if result["stderr"]:
        print(result["stderr"], file=sys.stderr, end="")
    sys.exit(result["returncode"])
