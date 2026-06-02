#!/usr/bin/env python3
"""
hook_session_end.py - Stop event hook (Module 7)
Fires when the Claude Code session ends.

Connects directly to Redis (port 6380) and Postgres (port 5433) via SSH tunnel
to collect session stats, then sends a plain-English summary to ALL Telegram users.
No MCP tools — this script is self-contained.
"""
from __future__ import annotations

import io
import json
import os
import socket
import sys
import time
from pathlib import Path

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

# ── Load .env ──────────────────────────────────────────────────────────────────
_ENV = Path(__file__).parent.parent / ".env"
if _ENV.exists():
    for _line in _ENV.read_text(encoding="utf-8").splitlines():
        if "=" in _line and not _line.startswith("#"):
            _k, _, _v = _line.partition("=")
            if _k.strip() not in os.environ:
                os.environ[_k.strip()] = _v.strip()

TG_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "")
TG_IDS: list[str] = []
for _key in ("TELEGRAM_ADMIN_CHAT_ID", "TELEGRAM_ADMIN_CHAT_ID_2"):
    for _part in os.environ.get(_key, "").replace(";", ",").split(","):
        if _part.strip() and _part.strip() not in TG_IDS:
            TG_IDS.append(_part.strip())

REDIS_HOST = os.environ.get("VPS_REDIS_HOST", "127.0.0.1")
REDIS_PORT = int(os.environ.get("VPS_REDIS_PORT", "6380"))
PG_DSN     = os.environ.get("VPS_PG_DSN", "postgresql://corvus:corvus-local-password@127.0.0.1:5433/careerbridge")


# ── Redis ──────────────────────────────────────────────────────────────────────

def _redis_llen(key: str) -> int:
    try:
        with socket.create_connection((REDIS_HOST, REDIS_PORT), timeout=3) as s:
            cmd = f"*2\r\n$4\r\nLLEN\r\n${len(key)}\r\n{key}\r\n"
            s.sendall(cmd.encode())
            reply = s.recv(256).decode(errors="replace").strip()
            if reply.startswith(":"):
                return int(reply[1:])
    except Exception:
        pass
    return -1


# ── Postgres ───────────────────────────────────────────────────────────────────

def _pg_job_stats() -> dict:
    try:
        import psycopg2
        with psycopg2.connect(PG_DSN, connect_timeout=5) as c:
            with c.cursor() as cur:
                cur.execute("SELECT status, count(*) FROM jobs GROUP BY status")
                return {row[0]: row[1] for row in cur.fetchall()}
    except Exception:
        return {}


def _pg_profile_count() -> int:
    try:
        import psycopg2
        with psycopg2.connect(PG_DSN, connect_timeout=5) as c:
            with c.cursor() as cur:
                cur.execute("SELECT count(*) FROM profiles")
                return cur.fetchone()[0]
    except Exception:
        return -1


def _pg_school_count() -> int:
    try:
        import psycopg2
        with psycopg2.connect(PG_DSN, connect_timeout=5) as c:
            with c.cursor() as cur:
                cur.execute("SELECT count(*) FROM schools WHERE criteria_score >= 1")
                return cur.fetchone()[0]
    except Exception:
        return -1


# ── Telegram ───────────────────────────────────────────────────────────────────

def _send(text: str) -> None:
    if not TG_TOKEN or not TG_IDS:
        return
    import urllib.request
    for chat_id in TG_IDS:
        try:
            body = json.dumps({"chat_id": chat_id, "text": text,
                               "parse_mode": "Markdown"}).encode()
            req = urllib.request.Request(
                f"https://api.telegram.org/bot{TG_TOKEN}/sendMessage",
                data=body, headers={"Content-Type": "application/json"},
            )
            urllib.request.urlopen(req, timeout=8)
        except Exception:
            pass


# ── Main ───────────────────────────────────────────────────────────────────────

def main() -> None:
    ts = time.strftime("%Y-%m-%d %H:%M UTC", time.gmtime())

    # Collect stats
    pending  = _redis_llen("corvus:pending_approvals")
    approved = _redis_llen("corvus:approved_jobs")
    by_status = _pg_job_stats()
    profiles  = _pg_profile_count()
    schools   = _pg_school_count()

    completed  = by_status.get("completed", 0)
    total_jobs = sum(by_status.values()) if by_status else 0

    # Build summary
    lines = [f"*Corvus session ended* — {ts}", ""]

    if pending >= 0:
        lines.append(f"Jobs waiting for review: *{pending}*")
    if approved >= 0:
        lines.append(f"Jobs approved and queued: *{approved}*")
    if completed:
        lines.append(f"Applications completed this run: *{completed}*")
    if total_jobs:
        lines.append(f"Total jobs on record: *{total_jobs}*")
    if schools >= 0:
        lines.append(f"Confirmed schools in database: *{schools}*")
    if profiles >= 0:
        lines.append(f"Active profiles: *{profiles}*")

    lines += ["", "_All systems standing by. Start a new session anytime._"]

    message = "\n".join(lines)
    _send(message)


if __name__ == "__main__":
    main()
