"""
queue_bridge.py — Polls corvus:approved_jobs Redis queue and dispatches
each job to the cb-core orchestrator for execution.

Called by Desktop Claude Code as a tool, not a standalone daemon.
The MCP bridge (vps_mcp) must be running before calling this.

Usage:
    python scripts/queue_bridge.py [--once]

  --once   Process all currently queued jobs then exit (default: loop forever)
"""
from __future__ import annotations

import argparse
import json
import os
import socket
import subprocess
import sys
import time
from pathlib import Path

CB_DIR  = Path(__file__).resolve().parent.parent
PYTHON  = os.environ.get("CB_PYTHON", "C:/Python314/python.exe")

REDIS_HOST = "127.0.0.1"
REDIS_PORT  = 6380
APPROVED_KEY  = "corvus:approved_jobs"
ASSESSMENT_KEY = "corvus:assessment_queue"
POLL_INTERVAL  = 15  # seconds


def _redis_cmd(*parts: str) -> bytes:
    with socket.create_connection((REDIS_HOST, REDIS_PORT), timeout=5) as sock:
        cmd = f"*{len(parts)}\r\n" + "".join(f"${len(p)}\r\n{p}\r\n" for p in parts)
        sock.sendall(cmd.encode())
        data = b""
        while True:
            chunk = sock.recv(4096)
            if not chunk:
                break
            data += chunk
            if b"\r\n" in data:
                break
        return data


def _lpop(key: str) -> str | None:
    """Atomically pop from left of Redis list. Returns None if empty."""
    try:
        reply = _redis_cmd("LPOP", key).decode(errors="replace").strip()
        if reply == "$-1" or reply.startswith("*-1") or reply == "-1":
            return None
        lines = reply.split("\r\n")
        if lines[0].startswith("$") and len(lines) > 1:
            return lines[1]
        if lines[0].startswith("+") or lines[0].startswith(":"):
            return None
        return lines[0] if lines[0] not in ("$-1",) else None
    except Exception:
        return None


def _rpush(key: str, value: str) -> None:
    try:
        _redis_cmd("RPUSH", key, value)
    except Exception:
        pass


def dispatch_job(job_payload: dict) -> dict:
    """
    Run the cb-core orchestrator for a single approved job.
    Returns {"ok": bool, "result": str}.
    """
    job_id = job_payload.get("job_id")
    url = job_payload.get("url", "")
    profile_id = job_payload.get("profile_id", "")

    if not url:
        return {"ok": False, "result": "no URL in payload"}

    # Invoke orchestrator as subprocess
    args = [
        PYTHON, "-m", "careerbridge.orchestrator",
        "--url", url,
        "--job-id", str(job_id or ""),
        "--profile", profile_id or "",
        "--mode", "apply",
    ]
    try:
        result = subprocess.run(
            args,
            capture_output=True, text=True, timeout=3600,
            cwd=str(CB_DIR)
        )
        output = (result.stdout + result.stderr).strip()
        ok = result.returncode == 0
        return {"ok": ok, "result": output[-2000:] if len(output) > 2000 else output}
    except subprocess.TimeoutExpired:
        return {"ok": False, "result": "timed out after 3600s"}
    except Exception as e:
        return {"ok": False, "result": str(e)}


def process_queue(once: bool = False):
    print(f"Queue bridge started. Polling {APPROVED_KEY} every {POLL_INTERVAL}s...")
    while True:
        payload_str = _lpop(APPROVED_KEY)
        if payload_str:
            try:
                payload = json.loads(payload_str)
            except Exception:
                payload = {"raw": payload_str}

            job_id = payload.get("job_id", "?")
            print(f"[{job_id}] Dispatching: {payload.get('url', '?')}")
            result = dispatch_job(payload)
            print(f"[{job_id}] Done: ok={result['ok']} — {result['result'][:200]}")

            # Write result back to Redis for VPS to pick up
            _rpush(
                "corvus:job_results",
                json.dumps({"job_id": job_id, "ok": result["ok"], "result": result["result"][:500]})
            )
        elif once:
            print("Queue empty — exiting (--once mode).")
            break
        else:
            time.sleep(POLL_INTERVAL)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--once", action="store_true", help="Process current queue then exit")
    args = parser.parse_args()
    process_queue(once=args.once)


if __name__ == "__main__":
    main()
