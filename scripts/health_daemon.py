"""
CareerBridge Health Daemon.

Polls all MCP ports every 30 seconds. Restarts any dead server immediately,
sends a Telegram alert, and logs the event. Backs off exponentially if a
server keeps crashing to avoid restart storms and Telegram spam.

Also monitors the VPS SSH tunnel (Redis:6380, Postgres:5433, Crawlee:3101).
If any tunnel port goes dark the daemon kills dead SSH processes and restarts
the tunnel, then alerts via Telegram. Port-binding is verified — process-alive
alone is not enough (zombie SSH processes hold no port bindings).

Run via Task Scheduler (see register_startup.ps1). Designed to run forever.
"""
from __future__ import annotations

import json
import logging
import os
import socket
import sqlite3
import ssl
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

VPS_HOST  = "root@77.42.91.185"
# Keys tried in order — cb_remote_agent is the permanent fallback that never
# gets regenerated; id_careerbridge is the primary but can be rotated.
SSH_KEYS  = [
    Path.home() / ".ssh" / "id_careerbridge",
    Path.home() / ".ssh" / "cb_remote_agent",
]
# Tunnel ports: local → VPS mapping (for alerting labels only)
TUNNEL_PORTS = {
    6380: "Redis (6380->VPS:6379)",
    5433: "Postgres (5433->VPS:5432)",
    3101: "Crawlee (3101->VPS:3100)",
}
TUNNEL_POLL_INTERVAL   = 60   # check tunnel every 60 s (less noisy than MCP 30 s)
VPS_CHECK_INTERVAL     = 300  # check VPS containers every 5 minutes
VPS_SSH_TIMEOUT        = 15   # seconds for SSH health check command

# Critical VPS containers — if any of these are unhealthy or missing, alert immediately
VPS_CRITICAL_CONTAINERS = {
    "corvus-postgres",
    "corvus-redis",
    "corvus-queue-worker",
    "corvus-browser-use",
    "corvus-rabbitmq",
}

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

def _tg_ssl_ctx() -> ssl.SSLContext:
    """SSL context that works even when the system has SSL-inspecting AV/proxy."""
    try:
        import certifi
        ctx = ssl.create_default_context(cafile=certifi.where())
        return ctx
    except Exception:
        pass
    # Last resort: skip verification (only used for outbound Telegram alerts)
    ctx = ssl.create_default_context()
    ctx.check_hostname = False
    ctx.verify_mode = ssl.CERT_NONE
    return ctx

_TG_SSL: ssl.SSLContext | None = None


def _tg_send(text: str) -> None:
    global _TG_SSL
    token = os.environ.get("TELEGRAM_BOT_TOKEN", "")
    raw   = os.environ.get("TELEGRAM_ADMIN_CHAT_ID", "").strip()
    if not token or not raw:
        return
    try:
        chat_id = int(raw)
    except ValueError:
        return
    if _TG_SSL is None:
        _TG_SSL = _tg_ssl_ctx()
    url  = f"https://api.telegram.org/bot{token}/sendMessage"
    body = json.dumps({"chat_id": chat_id, "text": text}).encode()
    req  = urllib.request.Request(url, data=body, headers={"Content-Type": "application/json"})
    try:
        urllib.request.urlopen(req, context=_TG_SSL, timeout=8)
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


# ── Tunnel management ─────────────────────────────────────────────────────────

def _tunnel_ports_up() -> list[int]:
    """Return list of tunnel ports that are currently DOWN."""
    return [p for p in TUNNEL_PORTS if not _is_up(p)]


def _kill_zombie_ssh() -> int:
    """Kill all ssh.exe processes. Returns number killed."""
    try:
        r = subprocess.run(
            ["taskkill", "/F", "/IM", "ssh.exe"],
            capture_output=True, text=True,
        )
        killed = r.stdout.count("SUCCESS")
        if killed:
            log.info("Killed %d zombie SSH process(es).", killed)
        return killed
    except Exception as e:
        log.warning("taskkill ssh.exe failed: %s", e)
        return 0


def _restart_tunnel() -> bool:
    """
    Kill dead SSH processes and start a fresh tunnel.
    Returns True if the tunnel ports come up within 8 seconds.
    """
    _kill_zombie_ssh()
    time.sleep(1)

    key = next((k for k in SSH_KEYS if k.exists()), None)
    ssh_exe = "C:/WINDOWS/System32/OpenSSH/ssh.exe"
    args = [
        ssh_exe,
        "-o", "StrictHostKeyChecking=no",
        "-o", "ServerAliveInterval=30",
        "-o", "ServerAliveCountMax=5",
        "-o", "ExitOnForwardFailure=yes",
        "-L", "6380:127.0.0.1:6379",
        "-L", "5433:127.0.0.1:5432",
        "-L", "3101:127.0.0.1:3100",
        "-N", VPS_HOST,
    ]
    if key:
        args = [ssh_exe, "-i", str(key)] + args[1:]

    try:
        subprocess.Popen(args, creationflags=subprocess.CREATE_NO_WINDOW)
    except Exception as e:
        log.error("Failed to start SSH tunnel: %s", e)
        return False

    # Wait up to 8 s for ports to bind
    for _ in range(8):
        time.sleep(1)
        if not _tunnel_ports_up():
            log.info("Tunnel restarted successfully — all ports bound.")
            return True

    down = _tunnel_ports_up()
    log.warning("Tunnel restarted but ports still down: %s", down)
    return False

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

@dataclass
class TunnelState:
    restart_count:   int   = 0
    last_restart_at: float = 0.0
    last_checked_at: float = 0.0
    alerted:         bool  = False

    def due(self) -> bool:
        return (time.monotonic() - self.last_checked_at) >= TUNNEL_POLL_INTERVAL

    def backoff_elapsed(self) -> bool:
        step  = min(self.restart_count, len(BACKOFF_STEPS) - 1)
        delay = BACKOFF_STEPS[step]
        return (time.monotonic() - self.last_restart_at) >= delay

    def reset(self) -> None:
        if self.restart_count > 0:
            log.info("Tunnel healthy again after %d restart(s).", self.restart_count)
        self.restart_count   = 0
        self.last_restart_at = 0.0
        self.alerted         = False


@dataclass
class VpsState:
    last_checked_at:  float = 0.0
    alerted_down:     bool  = False
    alerted_services: set   = field(default_factory=set)  # containers alerted as unhealthy

    def due(self) -> bool:
        return (time.monotonic() - self.last_checked_at) >= VPS_CHECK_INTERVAL


def _vps_check() -> dict:
    """
    SSH into VPS, return container health status.
    Returns dict with keys:
      'reachable': bool
      'unhealthy': list[str]  — container names in unhealthy/exited state
      'missing':   list[str]  — critical containers not present at all
      'error':     str | None
    """
    key = next((k for k in SSH_KEYS if k.exists()), None)
    ssh_exe = "C:/WINDOWS/System32/OpenSSH/ssh.exe"
    cmd = (
        "docker ps -a --format '{{.Names}}|{{.Status}}' "
        "--filter 'name=corvus-'"
    )
    args = [ssh_exe, "-o", "StrictHostKeyChecking=no",
            "-o", f"ConnectTimeout={VPS_SSH_TIMEOUT}",
            "-o", "BatchMode=yes"]
    if key:
        args += ["-i", str(key)]
    args += [VPS_HOST, cmd]

    try:
        r = subprocess.run(
            args, capture_output=True, text=True,
            timeout=VPS_SSH_TIMEOUT + 5,
        )
        if r.returncode != 0:
            return {"reachable": False, "unhealthy": [], "missing": [], "error": r.stderr.strip()[:200]}

        running: dict[str, str] = {}
        for line in r.stdout.strip().splitlines():
            if "|" not in line:
                continue
            name, status = line.split("|", 1)
            running[name.strip()] = status.strip()

        unhealthy = [
            n for n, s in running.items()
            if "unhealthy" in s.lower() or "exited" in s.lower() or "dead" in s.lower()
        ]
        missing = [c for c in VPS_CRITICAL_CONTAINERS if c not in running]
        return {"reachable": True, "unhealthy": unhealthy, "missing": missing, "error": None}

    except subprocess.TimeoutExpired:
        return {"reachable": False, "unhealthy": [], "missing": [], "error": "SSH timed out"}
    except Exception as exc:
        return {"reachable": False, "unhealthy": [], "missing": [], "error": str(exc)[:200]}


def run() -> None:
    log.info("Health daemon starting. Monitoring %d MCP servers + VPS tunnel + VPS containers.", len(SERVERS))
    _db_init()
    _tg_send("CareerBridge health daemon started. Monitoring all MCPs + VPS tunnel + VPS containers.")

    mcp_states    = {port: PortState(mod=mod, port=port) for mod, port in SERVERS}
    tunnel_state  = TunnelState()
    vps_state     = VpsState()

    while True:
        # ── MCP server checks ─────────────────────────────────────────────────
        for mod, port in SERVERS:
            st = mcp_states[port]

            if _is_up(port):
                st.reset()
                continue

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

            time.sleep(STARTUP_GRACE)

        # ── VPS tunnel check (every TUNNEL_POLL_INTERVAL seconds) ─────────────
        if tunnel_state.due():
            tunnel_state.last_checked_at = time.monotonic()
            down_ports = _tunnel_ports_up()

            if not down_ports:
                tunnel_state.reset()
            elif tunnel_state.backoff_elapsed():
                tunnel_state.restart_count  += 1
                tunnel_state.last_restart_at = time.monotonic()
                down_labels = [TUNNEL_PORTS[p] for p in down_ports]
                log.warning("Tunnel DOWN — ports %s — restart #%d",
                            down_labels, tunnel_state.restart_count)

                ok = _restart_tunnel()

                if ok:
                    _tg_send(
                        f"[TUNNEL] SSH tunnel was down ({', '.join(down_labels)}). "
                        f"Auto-restarted successfully (attempt #{tunnel_state.restart_count})."
                    )
                    tunnel_state.reset()
                else:
                    if tunnel_state.restart_count <= ALERT_AFTER:
                        _tg_send(
                            f"[TUNNEL] SSH tunnel restart #{tunnel_state.restart_count} failed. "
                            f"Down ports: {', '.join(down_labels)}. Will retry."
                        )
                    elif not tunnel_state.alerted:
                        tunnel_state.alerted = True
                        _db_write_issue("vps_ssh_tunnel", 6380, tunnel_state.restart_count)
                        _tg_send(
                            f"[TUNNEL] SSH tunnel has failed {tunnel_state.restart_count} times. "
                            f"Possible auth issue (check SSH keys). "
                            f"Logged to health_issues. Manual intervention may be needed."
                        )

        # ── VPS container health check (every VPS_CHECK_INTERVAL seconds) ──────
        if vps_state.due():
            vps_state.last_checked_at = time.monotonic()
            result = _vps_check()

            if not result["reachable"]:
                if not vps_state.alerted_down:
                    vps_state.alerted_down = True
                    log.error("VPS unreachable: %s", result["error"])
                    _tg_send(
                        f"[VPS] VPS 77.42.91.185 is UNREACHABLE. "
                        f"Error: {result['error']}. Check server status immediately."
                    )
                    _db_write_issue("vps_host", 0, 1)
            else:
                if vps_state.alerted_down:
                    vps_state.alerted_down = False
                    log.info("VPS reachable again.")
                    _tg_send("[VPS] VPS 77.42.91.185 is reachable again.")

                problems = result["unhealthy"] + result["missing"]
                new_problems = [p for p in problems if p not in vps_state.alerted_services]
                recovered    = [p for p in vps_state.alerted_services if p not in problems]

                for name in recovered:
                    vps_state.alerted_services.discard(name)
                    log.info("VPS container recovered: %s", name)
                    _tg_send(f"[VPS] Container '{name}' recovered and is healthy.")

                for name in new_problems:
                    vps_state.alerted_services.add(name)
                    tag = "UNHEALTHY" if name in result["unhealthy"] else "MISSING"
                    log.error("VPS container %s: %s", tag, name)
                    _tg_send(
                        f"[VPS] Container '{name}' is {tag}. "
                        f"VPS watchdog should auto-recover; check Dozzle at :9999 if it persists."
                    )
                    _db_write_issue(f"vps_container:{name}", 0, 1)

                if not problems:
                    log.debug("VPS containers healthy.")

        time.sleep(POLL_INTERVAL)


if __name__ == "__main__":
    try:
        run()
    except KeyboardInterrupt:
        log.info("Health daemon stopped by user.")
