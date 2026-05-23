"""
CareerBridge Health Daemon.

Polls all MCP ports every 30 seconds. Restarts any dead server immediately,
sends a Telegram alert, and logs the event. Backs off exponentially if a
server keeps crashing to avoid restart storms and Telegram spam.

Run via Task Scheduler (see register_startup.ps1). Designed to run forever.
"""
from __future__ import annotations

import json
import logging
import os
import socket
import sqlite3
import subprocess
import sys
import time
import urllib.request
from dataclasses import dataclass, field
from datetime import datetime, timezone
from logging.handlers import RotatingFileHandler
from pathlib import Path

# ── Config ────────────────────────────────────────────────────────────────────

CB_DIR  = Path(os.environ.get("CB_DIR", Path(__file__).resolve().parent.parent))
PYTHON  = Path(os.environ.get("CB_PYTHON", "C:/Python314/python.exe"))
LOG     = CB_DIR / "logs" / "health.log"
DB      = CB_DIR / "careerbridge.db"

POLL_INTERVAL = 30          # seconds between full health checks
STARTUP_GRACE = 10          # seconds to wait after restart before re-checking
BACKOFF_STEPS = [0, 60, 120, 300, 600]  # seconds to wait before Nth restart attempt
ALERT_AFTER   = 3           # send "persistent failure" alert after this many restarts

SERVERS = [
    ("humanizer_mcp.server", 8701),
    ("capture_mcp.server",   8702),
    ("uia_mcp.server",       8703),
    ("browser_mcp.server",   8704),
    ("gemini_mcp.server",    8705),
    ("telegram_mcp.server",  8706),
    ("answer_mcp.server",    8707),
    ("sqlite_mcp.server",    8708),
    ("memory_mcp.server",    8709),
    ("dom_mcp.server",       8710),
    ("cdp_mcp.server",       8712),
    ("vps_mcp.server",       8713),
]

# ── Logging ───────────────────────────────────────────────────────────────────

LOG.parent.mkdir(parents=True, exist_ok=True)

_fmt = logging.Formatter("%(asctime)s %(levelname)-8s %(message)s", datefmt="%Y-%m-%d %H:%M:%S")
_fh  = RotatingFileHandler(str(LOG), maxBytes=5 * 1024 * 1024, backupCount=3, encoding="utf-8")
_fh.setFormatter(_fmt)
_sh  = logging.StreamHandler(sys.stdout)
_sh.setFormatter(_fmt)

log = logging.getLogger("health")
log.setLevel(logging.INFO)
log.addHandler(_fh)
log.addHandler(_sh)

# ── Telegram (direct HTTP — no MCP dependency) ────────────────────────────────

def _tg_send(text: str) -> None:
    token = os.environ.get("TELEGRAM_BOT_TOKEN", "")
    raw   = os.environ.get("TELEGRAM_ADMIN_CHAT_ID", "").strip()
    if not token or not raw:
        return
    try:
        chat_id = int(raw)
    except ValueError:
        return
    url  = f"https://api.telegram.org/bot{token}/sendMessage"
    body = json.dumps({"chat_id": chat_id, "text": text}).encode()
    req  = urllib.request.Request(url, data=body, headers={"Content-Type": "application/json"})
    try:
        urllib.request.urlopen(req, timeout=8)
    except Exception as exc:
        log.warning("Telegram send failed: %s", exc)

# ── Database ─────────────────────────────────────────────────────────────────

def _db_init() -> None:
    """Create health_issues table if it doesn't exist."""
    try:
        with sqlite3.connect(str(DB)) as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS health_issues (
                    id            INTEGER PRIMARY KEY AUTOINCREMENT,
                    created_at    TEXT NOT NULL,
                    module        TEXT NOT NULL,
                    port          INTEGER NOT NULL,
                    restart_count INTEGER NOT NULL,
                    status        TEXT NOT NULL DEFAULT 'pending'
                )
            """)
            conn.commit()
    except Exception as exc:
        log.warning("DB init failed: %s", exc)


def _db_write_issue(mod: str, port: int, restart_count: int) -> None:
    """Record a persistent failure for Claude Code to pick up and fix."""
    try:
        now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
        with sqlite3.connect(str(DB)) as conn:
            conn.execute(
                "INSERT INTO health_issues (created_at, module, port, restart_count, status) "
                "VALUES (?, ?, ?, ?, 'pending')",
                (now, mod, port, restart_count),
            )
            conn.commit()
    except Exception as exc:
        log.warning("DB write failed: %s", exc)


# ── Port probe ────────────────────────────────────────────────────────────────

def _is_up(port: int) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.settimeout(1)
        return s.connect_ex(("127.0.0.1", port)) == 0

# ── Process restart ───────────────────────────────────────────────────────────

def _start_server(mod: str, port: int) -> None:
    subprocess.Popen(
        [str(PYTHON), "-m", mod, "--http", str(port)],
        cwd=str(CB_DIR),
        creationflags=subprocess.CREATE_NO_WINDOW,
    )

# ── Port state tracking ───────────────────────────────────────────────────────

@dataclass
class PortState:
    mod:              str
    port:             int
    restart_count:    int   = 0
    last_restart_at:  float = 0.0
    alerted:          bool  = False   # "persistent failure" alert already sent

    def backoff_elapsed(self) -> bool:
        step  = min(self.restart_count, len(BACKOFF_STEPS) - 1)
        delay = BACKOFF_STEPS[step]
        return (time.monotonic() - self.last_restart_at) >= delay

    def reset(self) -> None:
        if self.restart_count > 0:
            log.info("Port %d (%s) is healthy again after %d restart(s).",
                     self.port, self.mod, self.restart_count)
        self.restart_count   = 0
        self.last_restart_at = 0.0
        self.alerted         = False

# ── Main loop ─────────────────────────────────────────────────────────────────

def run() -> None:
    log.info("Health daemon starting. Monitoring %d MCP servers.", len(SERVERS))
    _db_init()
    _tg_send("CareerBridge health daemon started. Monitoring all MCPs.")

    states = {port: PortState(mod=mod, port=port) for mod, port in SERVERS}

    while True:
        for mod, port in SERVERS:
            st = states[port]

            if _is_up(port):
                st.reset()
                continue

            # Port is down — check if we should restart yet (backoff)
            if not st.backoff_elapsed():
                continue

            st.restart_count  += 1
            st.last_restart_at = time.monotonic()

            log.warning("Port %d (%s) DOWN — restart #%d", port, mod, st.restart_count)
            _start_server(mod, port)

            if st.restart_count <= ALERT_AFTER:
                _tg_send(f"[HEALTH] {mod} (port {port}) was down. Restarted (#{st.restart_count}).")
            elif not st.alerted:
                st.alerted = True
                _db_write_issue(mod, port, st.restart_count)
                _tg_send(
                    f"[HEALTH] {mod} (port {port}) has failed {st.restart_count} times. "
                    f"Logged to health_issues table. Claude Code will diagnose and fix on next active session."
                )

            time.sleep(STARTUP_GRACE)   # let the new process bind before next check

        time.sleep(POLL_INTERVAL)


if __name__ == "__main__":
    try:
        run()
    except KeyboardInterrupt:
        log.info("Health daemon stopped by user.")
