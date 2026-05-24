"""
choose_node.py — PreToolUse hook for mcp__vps__approve_job.
If multiple execution nodes are online, block and instruct Claude
to present an AskUserQuestion node-picker before proceeding.
"""
import json
import os
import socket
import sys

REDIS_HOST = "127.0.0.1"
REDIS_PORT = int(os.environ.get("REDIS_PORT", "6380"))


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

    # Find all online node heartbeat keys (corvus:node:<id> only, not sub-keys)
    node_keys = [k for k in _redis_keys("corvus:node:*") if k.count(":") == 2]

    if len(node_keys) <= 1:
        # Only local machine — pass through
        sys.exit(0)

    # Build node list
    nodes = []
    for key in node_keys:
        raw = _redis_get(key)
        if raw:
            try:
                nodes.append(json.loads(raw))
            except Exception:
                node_id = key.split(":")[-1]
                nodes.append({"node_id": node_id, "hostname": node_id, "capabilities": "full"})

    node_lines = "\n".join(
        f"    node_id='{n.get('node_id','?')}' | host='{n.get('hostname','?')}' | caps='{n.get('capabilities','full')}'"
        for n in nodes
    )

    reminder = (
        f"SYSTEM REMINDER: Multiple execution computers are online. "
        f"Before approving job {job_id}, ask the user which computer should run it.\n\n"
        f"Online computers:\n{node_lines}\n\n"
        f"Steps:\n"
        f"1. Call AskUserQuestion:\n"
        f"     question: 'Which computer should handle this job?'\n"
        f"     header: 'Choose Computer'\n"
        f"     multiSelect: false\n"
        f"     options: one option per online node (label=hostname, description=capabilities)\n"
        f"              PLUS label='This Computer', description='Run on the main desktop'\n\n"
        f"2. If the user picks 'This Computer':\n"
        f"     Call mcp__vps__approve_job(job_id={job_id}) normally.\n\n"
        f"3. If the user picks a remote node:\n"
        f"     Call mcp__vps__dispatch_job_to_node(job_id={job_id}, node_id='<chosen_node_id>').\n"
        f"     Do NOT call approve_job — dispatch_job_to_node handles approval + queuing.\n\n"
        f"Do NOT retry the blocked approve_job call."
    )

    print(json.dumps({"type": "system", "content": reminder}))
    sys.exit(2)


if __name__ == "__main__":
    main()
