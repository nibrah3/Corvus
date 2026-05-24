"""
gate_client.py — Human gate protocol: subprocess → Redis → Claude Code hook → Redis.

When assessment_pipeline.py hits a free-text field it cannot auto-answer confidently:
  1. Writes a gate request to Redis  corvus:pending_gates  (RPUSH)
  2. Blocks polling  corvus:gate_responses:{gate_id}  until answered or timeout
  3. Claude Code's UserPromptSubmit hook sees the pending gate, presents AskUserQuestion
  4. User approves/edits; hook writes answer back to Redis
  5. poll_for_answer() returns the text

This keeps Claude Code as the brain for ALL human decisions.
Telegram is secondary notification only (not the primary gate mechanism).
"""
from __future__ import annotations

import json
import os
import socket
import time
import uuid
from typing import Optional

_REDIS_HOST = "127.0.0.1"
_REDIS_PORT = int(os.environ.get("REDIS_PORT", "6380"))
_GATES_KEY  = "corvus:pending_gates"
_RESP_PREFIX= "corvus:gate_response:"
_GATE_TTL   = 600   # 10 minutes
_POLL_SLEEP = 1.5   # seconds between response polls


def _redis(cmd: list) -> str:
    parts = cmd
    wire = f"*{len(parts)}\r\n" + "".join(f"${len(str(p))}\r\n{p}\r\n" for p in parts)
    try:
        with socket.create_connection((_REDIS_HOST, _REDIS_PORT), timeout=4) as s:
            s.sendall(wire.encode())
            return s.recv(4096).decode(errors="replace")
    except Exception as e:
        return f"-ERR {e}\r\n"


def _rpush(key: str, value: str) -> None:
    _redis(["RPUSH", key, value])


def _setex(key: str, ttl: int, value: str) -> None:
    _redis(["SETEX", key, str(ttl), value])


def _get(key: str) -> Optional[str]:
    reply = _redis(["GET", key])
    if reply.startswith("$-1") or reply.startswith("-"):
        return None
    lines = reply.split("\r\n")
    return lines[1] if len(lines) > 1 else None


def _del(key: str) -> None:
    _redis(["DEL", key])


# ── Public API ────────────────────────────────────────────────────────────────

def request_gate(
    field_label: str,
    draft: str,
    job_id=None,
    profile_id: str = "",
    gate_type: str = "assessment_gate",
    timeout: float = 300.0,
) -> Optional[str]:
    """
    Push a human-gate request and block until Claude Code responds.

    Returns the approved/edited answer text, or None if skipped/timed out.
    """
    gate_id = str(uuid.uuid4())[:8]
    payload = json.dumps({
        "gate_id":    gate_id,
        "type":       gate_type,
        "field":      field_label,
        "draft":      draft[:2000],
        "job_id":     job_id,
        "profile_id": profile_id,
        "created_at": time.time(),
    })
    _rpush(_GATES_KEY, payload)

    # Also set a readable key so hook can LRANGE and display nicely
    _setex(f"corvus:gate_pending:{gate_id}", _GATE_TTL, payload)

    return _poll_for_answer(gate_id, timeout)


def _poll_for_answer(gate_id: str, timeout: float) -> Optional[str]:
    resp_key = _RESP_PREFIX + gate_id
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        raw = _get(resp_key)
        if raw is not None:
            _del(resp_key)
            _del(f"corvus:gate_pending:{gate_id}")
            try:
                data = json.loads(raw)
                action = data.get("action", "approve")
                if action == "skip":
                    return None
                return data.get("answer") or None
            except json.JSONDecodeError:
                return raw.strip() or None
        time.sleep(_POLL_SLEEP)
    return None


def answer_gate(gate_id: str, action: str, answer: str = "") -> None:
    """
    Called by Claude Code (via hook or direct tool call) to respond to a gate.
    action: 'approve' | 'edit' | 'skip'
    """
    resp_key = _RESP_PREFIX + gate_id
    payload  = json.dumps({"gate_id": gate_id, "action": action, "answer": answer})
    _setex(resp_key, _GATE_TTL, payload)
    _del(f"corvus:gate_pending:{gate_id}")


def pending_gates() -> list[dict]:
    """Return all currently pending gate requests."""
    reply = _redis(["LRANGE", _GATES_KEY, "0", "-1"])
    results = []
    for line in reply.split("\r\n"):
        if line.startswith("{"):
            try:
                results.append(json.loads(line))
            except json.JSONDecodeError:
                pass
    return results


def clear_gate_from_queue(gate_id: str) -> None:
    """Remove a specific gate from the pending queue after it's answered."""
    # LRANGE → filter → reconstruct (Redis has no LREM by value efficiently)
    # We use LREM count=1 which removes first matching element
    try:
        all_raw = _redis(["LRANGE", _GATES_KEY, "0", "-1"])
        for line in all_raw.split("\r\n"):
            if line.startswith("{"):
                try:
                    item = json.loads(line)
                    if item.get("gate_id") == gate_id:
                        _redis(["LREM", _GATES_KEY, "1", line])
                        break
                except json.JSONDecodeError:
                    pass
    except Exception:
        pass
