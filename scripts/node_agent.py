"""
node_agent.py — Corvus execution node agent for secondary computers.
Heartbeats Redis every 30 s and processes tasks dispatched from the main desktop.

Usage:
  python node_agent.py --node-id node2 --capabilities "humanizer,capture,browser"

The main desktop's Redis must be reachable (direct LAN or SSH tunnel).
Set REDIS_HOST and REDIS_PORT in the .env to point at the main desktop.
"""
import argparse
import json
import os
import platform
import socket
import subprocess
import sys
import threading
import time


# ── Load .env ──────────────────────────────────────────────────────────────────

def _load_env():
    base = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    for path in [os.path.join(base, ".env"), os.path.join(base, "runtime", ".env")]:
        if os.path.exists(path):
            with open(path) as f:
                for line in f:
                    line = line.strip()
                    if line and not line.startswith("#") and "=" in line:
                        k, _, v = line.partition("=")
                        k, v = k.strip(), v.strip()
                        if k not in os.environ:
                            os.environ[k] = v
            return


_load_env()

REDIS_HOST = os.environ.get("REDIS_HOST", "127.0.0.1")
REDIS_PORT = int(os.environ.get("REDIS_PORT", "6380"))
HEARTBEAT_INTERVAL = 30
BLPOP_TIMEOUT = 30


# ── Redis helpers ──────────────────────────────────────────────────────────────

def _redis_cmd(*parts: str) -> str:
    with socket.create_connection((REDIS_HOST, REDIS_PORT), timeout=5) as sock:
        cmd = f"*{len(parts)}\r\n" + "".join(f"${len(p)}\r\n{p}\r\n" for p in parts)
        sock.sendall(cmd.encode())
        data = b""
        while True:
            chunk = sock.recv(4096)
            if not chunk:
                break
            data += chunk
            if data.endswith(b"\r\n"):
                break
        return data.decode(errors="replace").strip()


def _redis_setex(key: str, ttl: int, value: str) -> None:
    _redis_cmd("SETEX", key, str(ttl), value)


def _redis_blpop(key: str, timeout: int) -> str | None:
    """Blocking pop; returns the value string or None on timeout."""
    try:
        with socket.create_connection((REDIS_HOST, REDIS_PORT), timeout=timeout + 5) as sock:
            cmd = f"*3\r\n$5\r\nBLPOP\r\n${len(key)}\r\n{key}\r\n${len(str(timeout))}\r\n{timeout}\r\n"
            sock.sendall(cmd.encode())
            sock.settimeout(timeout + 5)
            data = b""
            while True:
                chunk = sock.recv(4096)
                if not chunk:
                    break
                data += chunk
                if data.endswith(b"\r\n"):
                    break
        reply = data.decode(errors="replace")
        # Nil reply on timeout: *-1 or $-1
        if reply.startswith(("*-1", "$-1")):
            return None
        # Array reply: *2 → [key, value]
        lines = reply.split("\r\n")
        if lines[0].startswith("*2"):
            i = 1
            # skip key bulk
            if lines[i].startswith("$"):
                i += 2
            # read value bulk
            if i < len(lines) and lines[i].startswith("$"):
                i += 1
                return lines[i] if i < len(lines) else None
        return None
    except Exception:
        return None


# ── Heartbeat thread ───────────────────────────────────────────────────────────

def _heartbeat_loop(node_id: str, hostname: str, capabilities: str, stop: threading.Event):
    while not stop.is_set():
        try:
            payload = json.dumps({
                "node_id":      node_id,
                "hostname":     hostname,
                "capabilities": capabilities,
                "last_seen":    int(time.time()),
                "platform":     platform.system(),
            })
            _redis_setex(f"corvus:node:{node_id}", 90, payload)
            print(f"[hb] {node_id} ok", flush=True)
        except Exception as e:
            print(f"[hb] error: {e}", flush=True)
        stop.wait(HEARTBEAT_INTERVAL)


# ── Task execution ─────────────────────────────────────────────────────────────

def _execute_task(task: dict, node_id: str):
    job_id = task.get("job_id")
    url    = task.get("url", "")
    print(f"[task] job={job_id} url={url}", flush=True)

    base   = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    script = os.path.join(base, "careerbridge", "run_node_task.py")

    try:
        result = subprocess.run(
            [sys.executable, script, "--task", json.dumps(task)],
            timeout=3600,
            capture_output=True,
            text=True,
        )
        print(f"[task] job={job_id} exit={result.returncode}", flush=True)
        if result.stdout:
            print(result.stdout[-2000:], flush=True)
        if result.stderr:
            print(f"[stderr] {result.stderr[-500:]}", flush=True)
    except subprocess.TimeoutExpired:
        print(f"[task] job={job_id} TIMEOUT", flush=True)
    except Exception as e:
        print(f"[task] job={job_id} error: {e}", flush=True)


# ── Main ───────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="Corvus execution node agent")
    parser.add_argument("--node-id",      required=True, help="Unique ID for this node, e.g. node2")
    parser.add_argument("--capabilities", default="full", help="Comma-separated capability tags")
    args = parser.parse_args()

    node_id     = args.node_id
    hostname    = platform.node()
    caps        = args.capabilities
    task_queue  = f"corvus:node:{node_id}:tasks"

    print(f"Corvus Node Agent — {node_id} ({hostname})", flush=True)
    print(f"  Redis:      {REDIS_HOST}:{REDIS_PORT}", flush=True)
    print(f"  Queue:      {task_queue}", flush=True)
    print(f"  Caps:       {caps}", flush=True)

    stop = threading.Event()
    threading.Thread(
        target=_heartbeat_loop, args=(node_id, hostname, caps, stop), daemon=True
    ).start()

    print("Waiting for tasks…", flush=True)
    try:
        while True:
            raw = _redis_blpop(task_queue, BLPOP_TIMEOUT)
            if raw is None:
                continue
            try:
                task = json.loads(raw)
            except Exception:
                print(f"[task] bad payload: {raw[:200]}", flush=True)
                continue
            _execute_task(task, node_id)
    except KeyboardInterrupt:
        print("Shutting down…", flush=True)
        stop.set()


if __name__ == "__main__":
    main()
