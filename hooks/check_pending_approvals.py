"""
check_pending_approvals.py — UserPromptSubmit hook.

Fires before every Claude Code message. Checks Redis for two kinds of pending items:

  1. corvus:pending_approvals  — jobs waiting for Apply/Skip decision
  2. corvus:pending_gates      — assessment free-text fields waiting for answer approval

For each pending item, injects a SYSTEM REMINDER so Claude Code presents it via
AskUserQuestion before doing anything else. This keeps Claude Code as the brain for
ALL human decisions — no Telegram/stdin gates needed.

Exit codes (Claude Code hook protocol):
  0  — proceed normally
  2  — block (not used here; we inject reminders and let Claude Code handle it)
"""
import json
import socket
import sys
import time

REDIS_HOST    = "127.0.0.1"
REDIS_PORT    = 6380
APPROVALS_KEY = "corvus:pending_approvals"
GATES_KEY     = "corvus:pending_gates"
TIMER_KEY     = "corvus:assessment_start_time"
TIMER_WARN_S  = 25 * 60   # warn after 25 minutes


def _redis_cmd(*parts: str) -> bytes:
    try:
        wire = f"*{len(parts)}\r\n" + "".join(f"${len(p)}\r\n{p}\r\n" for p in parts)
        with socket.create_connection((REDIS_HOST, REDIS_PORT), timeout=2) as s:
            s.sendall(wire.encode())
            return s.recv(4096)
    except Exception:
        return b""


def _get(key: str) -> str | None:
    reply = _redis_cmd("GET", key).decode(errors="replace")
    lines = reply.split("\r\n")
    if lines[0].startswith("$-1") or lines[0].startswith("-"):
        return None
    return lines[1] if len(lines) > 1 else None


def _llen(key: str) -> int:
    reply = _redis_cmd("LLEN", key).decode(errors="replace").strip()
    try:
        return int(reply.lstrip(":"))
    except ValueError:
        return 0


def _lrange(key: str, start: int = 0, stop: int = 2) -> list[dict]:
    reply = _redis_cmd("LRANGE", key, str(start), str(stop)).decode(errors="replace")
    results = []
    for line in reply.split("\r\n"):
        line = line.strip()
        if line.startswith("{"):
            try:
                results.append(json.loads(line))
            except json.JSONDecodeError:
                pass
    return results


def ix_running() -> bool:
    try:
        with socket.create_connection(("127.0.0.1", 53200), timeout=1):
            return True
    except Exception:
        return False


def main() -> None:
    hostname  = socket.gethostname()
    ix_status = "running" if ix_running() else "NOT running"
    messages  = []

    # ── 1. Job approval queue ─────────────────────────────────────────────────
    job_count = _llen(APPROVALS_KEY)
    if job_count > 0:
        messages.append(
            f"SYSTEM REMINDER [{hostname}]: {job_count} job(s) awaiting approval. "
            f"IXBrowser: {ix_status}. "
            f"Call mcp__vps__get_pending_approvals then present each via AskUserQuestion "
            f"with options [Apply] [Skip] [More Info]. "
            f"If IXBrowser is not running add [Launch IXBrowser] option — "
            f"run `python D:\\cb-core\\scripts\\check_ixbrowser.py --launch`."
        )

    # ── 2. Assessment human gates ──────────────────────────────────────────────
    gate_count = _llen(GATES_KEY)
    if gate_count > 0:
        gates = _lrange(GATES_KEY, 0, 2)  # show up to 3
        gate_details = []
        for g in gates:
            gid   = g.get("gate_id", "?")
            field = g.get("field", "unknown field")
            draft = (g.get("draft") or "")[:300]
            gate_details.append(
                f'  gate_id={gid!r} field={field!r} draft={draft!r}'
            )

        detail_str = "\n".join(gate_details)
        messages.append(
            f"SYSTEM REMINDER [{hostname}]: {gate_count} assessment gate(s) waiting for answer approval.\n"
            f"{detail_str}\n"
            f"For each gate: present the draft answer via AskUserQuestion with options "
            f"[✅ Approve] [✏️ Edit] [⏭ Skip]. "
            f"Then call: python D:\\cb-core\\hooks\\answer_gate.py <gate_id> approve|edit|skip [answer]"
        )

    # ── 3. Assessment timer ───────────────────────────────────────────────────
    start_raw = _get(TIMER_KEY)
    if start_raw:
        try:
            elapsed = time.time() - float(start_raw)
            if elapsed > TIMER_WARN_S:
                minutes = int(elapsed / 60)
                messages.append(
                    f"SYSTEM REMINDER [{hostname}]: Assessment has been running {minutes} minutes. "
                    "Some assessments have time limits (typically 30–60 min). "
                    "Verify the current page state with a screenshot if you haven't recently."
                )
        except Exception:
            pass

    if messages:
        combined = "\n\n".join(messages)
        print(json.dumps({"type": "system", "content": combined}))

    sys.exit(0)


if __name__ == "__main__":
    main()
