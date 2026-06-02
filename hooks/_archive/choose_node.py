"""
choose_node.py — PreToolUse hook for mcp__vps__approve_job.

Checks if multiple execution nodes are online. If so, checks .defaults.json
for a saved node preference. If a default is set, uses it silently.
Only blocks to ask the user when multiple nodes are online AND no default is set.
"""
import json
import os
import socket
import sys
from pathlib import Path

REDIS_HOST = "127.0.0.1"
REDIS_PORT = int(os.environ.get("REDIS_PORT", "6380"))
DEFAULTS_FILE = Path(__file__).parent.parent / ".defaults.json"


def _defaults() -> dict:
    try:
        return json.loads(DEFAULTS_FILE.read_text(encoding="utf-8"))
    except Exception:
        return {}


def _redis_raw(*parts: str) -> str:
    try:
        with socket.create_connection((REDIS_HOST, REDIS_PORT), timeout=3) as sock:
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
        return data.decode(errors="replace")
    except Exception:
        return ""


def _redis_keys(pattern: str) -> list:
    reply = _redis_raw("KEYS", pattern)
    lines = reply.split("\r\n")
    results = []
    i = 0
    if not lines or not lines[i].startswith("*"):
        return results
    try:
        count = int(lines[i][1:])
    except ValueError:
        return results
    i += 1
    for _ in range(count):
        if i >= len(lines):
            break
        if lines[i].startswith("$"):
            i += 1
            if i < len(lines):
                results.append(lines[i])
            i += 1
    return results


def _redis_get(key: str) -> str | None:
    reply = _redis_raw("GET", key)
    if reply.startswith("$-1"):
        return None
    lines = reply.split("\r\n")
    if lines[0].startswith("$"):
        return lines[1] if len(lines) > 1 else None
    return None


def main():
    try:
        ctx = json.loads(sys.stdin.read() or "{}")
    except Exception:
        sys.exit(0)

    job_id = ctx.get("tool_input", {}).get("job_id")

    # Only intercept if multiple nodes are online
    node_keys = [k for k in _redis_keys("corvus:node:*") if k.count(":") == 2]
    if len(node_keys) <= 1:
        sys.exit(0)

    # Check saved default
    default_node = _defaults().get("node_id", "local")

    # Build the full node list for the "Choose another" branch
    nodes = []
    for key in node_keys:
        raw = _redis_get(key)
        if raw:
            try:
                nodes.append(json.loads(raw))
            except Exception:
                node_id = key.split(":")[-1]
                nodes.append({"node_id": node_id, "hostname": node_id, "capabilities": "full"})

    all_node_lines = "\n".join(
        f"      • {n.get('hostname','?')} (node_id='{n.get('node_id','?')}')" for n in nodes
    )
    defaults_path = str(DEFAULTS_FILE)

    if default_node and default_node != "ask":
        default_label = "This Computer" if default_node == "local" else default_node
        dispatch_instruction = (
            f"    b. Call approve_job normally (this machine)."
            if default_node == "local"
            else f"    b. Call mcp__vps__dispatch_job_to_node(job_id={job_id}, node_id='{default_node}'). Do NOT call approve_job."
        )
        print(json.dumps({
            "type": "system",
            "content": (
                f"SYSTEM REMINDER: Default computer is '{default_label}' for job {job_id}.\n\n"
                f"YOUR TASK:\n"
                f"  Present AskUserQuestion:\n"
                f"    question: 'Which computer should run this job?'\n"
                f"    options:\n"
                f"      label: 'Use {default_label}' — description: 'Continue with your saved default.'\n"
                f"      label: 'Choose another' — description: 'Pick a different computer.'\n\n"
                f"  If user picks 'Use {default_label}':\n"
                f"    a. Read {defaults_path}, ensure node_id='{default_node}', write back.\n"
                f"{dispatch_instruction}\n\n"
                f"  If user picks 'Choose another':\n"
                f"    Present all online computers as buttons:\n"
                f"{all_node_lines}\n"
                f"    Plus 'This Computer'.\n"
                f"    After user picks:\n"
                f"      a. Read {defaults_path}, update 'node_id' to chosen node_id (or 'local'), write back.\n"
                f"      b. If 'This Computer': call approve_job normally.\n"
                f"         If remote: call mcp__vps__dispatch_job_to_node(job_id={job_id}, node_id=<id>)."
            )
        }))
        sys.exit(2)

    # No default set — ask once, show all options, save the answer
    print(json.dumps({
        "type": "system",
        "content": (
            f"SYSTEM REMINDER: Multiple computers are online. Ask the user which one to use "
            f"for job {job_id}.\n\n"
            f"Steps:\n"
            f"1. AskUserQuestion:\n"
            f"     question: 'Which computer should handle this job?'\n"
            f"     options: one per node (label=hostname) + label='This Computer'\n"
            f"     Each option description: 'Your choice will be saved as your default.'\n\n"
            f"Online computers:\n{all_node_lines}\n\n"
            f"2. After user picks:\n"
            f"   a. Read {defaults_path}, set node_id to the chosen node_id (or 'local' for "
            f"      'This Computer'), write back.\n"
            f"   b. If 'This Computer': call approve_job normally.\n"
            f"      If remote: call mcp__vps__dispatch_job_to_node(job_id={job_id}, node_id=<id>).\n\n"
            f"This question will NOT be asked again once a default is saved."
        )
    }))
    sys.exit(2)


if __name__ == "__main__":
    main()
