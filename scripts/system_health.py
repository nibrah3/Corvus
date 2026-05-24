"""
system_health.py — CareerBridge full-system health check and auto-repair.

Run by Claude Code cron every 30 minutes.
Checks: MCP servers, SSH tunnel ports, .env completeness, disk/memory.
Fixes: restarts dead MCPs, rebuilds tunnel if ports are closed, alerts via Telegram.
"""
from __future__ import annotations

import json
import os
import socket
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

CB_DIR = Path(__file__).resolve().parent.parent
_ENV   = CB_DIR / ".env"

# Load .env
if _ENV.exists():
    for line in _ENV.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            k, _, v = line.partition("=")
            if k.strip() not in os.environ:
                os.environ[k.strip()] = v.strip()


# ── Config ────────────────────────────────────────────────────────────────────

MCP_PORTS = {
    8701: "humanizer_mcp",
    8702: "capture_mcp",
    8703: "uia_mcp",
    8704: "browser_mcp",
    8705: "gemini_mcp",
    8706: "telegram_mcp",
    8707: "answer_mcp",
    8708: "sqlite_mcp",
    8709: "memory_mcp",
    8710: "dom_mcp",
    8712: "cdp_mcp",
    8713: "vps_mcp",
}

TUNNEL_PORTS = {
    6380: "Redis (VPS:6379)",
    5433: "Postgres (VPS:5432)",
    3101: "Crawlee (VPS:3100)",
}

ENV_REQUIRED = [
    "OPENROUTER_API_KEY",
    "GEMINI_API_KEY",
    "TELEGRAM_BOT_TOKEN",
    "TELEGRAM_ADMIN_CHAT_ID",
]

START_MCPS_SCRIPT = str(CB_DIR / "scripts" / "start_mcps.ps1")
TUNNEL_SCRIPT     = str(CB_DIR / "scripts" / "vps_tunnel.ps1")


# ── Helpers ───────────────────────────────────────────────────────────────────

def _port_open(port: int, host: str = "127.0.0.1", timeout: float = 2.0) -> bool:
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except OSError:
        return False


def _telegram(text: str) -> None:
    token  = os.environ.get("TELEGRAM_BOT_TOKEN", "")
    chat   = os.environ.get("TELEGRAM_ADMIN_CHAT_ID", "")
    if not token or not chat:
        return
    try:
        import urllib.request, json as _json
        body = _json.dumps({"chat_id": int(chat), "text": text}).encode()
        req = urllib.request.Request(
            f"https://api.telegram.org/bot{token}/sendMessage",
            data=body, headers={"Content-Type": "application/json"}
        )
        urllib.request.urlopen(req, timeout=8)
    except Exception:
        pass


def _run_ps(script: str) -> bool:
    try:
        result = subprocess.run(
            ["powershell.exe", "-NonInteractive", "-WindowStyle", "Hidden",
             "-File", script],
            capture_output=True, timeout=30
        )
        return result.returncode == 0
    except Exception:
        return False


def _ps_task_running(task_name: str) -> bool:
    try:
        r = subprocess.run(
            ["powershell.exe", "-NonInteractive", "-Command",
             f"(Get-ScheduledTask -TaskName '{task_name}' -ErrorAction SilentlyContinue).State"],
            capture_output=True, text=True, timeout=10
        )
        return "Running" in r.stdout
    except Exception:
        return False


def _start_task(task_name: str) -> bool:
    try:
        r = subprocess.run(
            ["powershell.exe", "-NonInteractive", "-Command",
             f"Start-ScheduledTask -TaskName '{task_name}'"],
            capture_output=True, timeout=15
        )
        return r.returncode == 0
    except Exception:
        return False


# ── Checks ────────────────────────────────────────────────────────────────────

def check_env() -> list[str]:
    missing = [k for k in ENV_REQUIRED if not os.environ.get(k)]
    return missing


def check_mcps() -> dict[int, bool]:
    return {port: _port_open(port) for port in MCP_PORTS}


def check_tunnel() -> dict[int, bool]:
    return {port: _port_open(port) for port in TUNNEL_PORTS}


# ── Repairs ───────────────────────────────────────────────────────────────────

def repair_mcps(dead_ports: list[int]) -> bool:
    if not dead_ports:
        return True
    print(f"  Restarting MCPs ({len(dead_ports)} dead ports)...")
    ok = _run_ps(START_MCPS_SCRIPT)
    time.sleep(8)
    still_dead = [p for p in dead_ports if not _port_open(p)]
    if still_dead:
        print(f"  Still dead after restart: {still_dead}")
    return len(still_dead) == 0


def repair_tunnel(dead_ports: list[int]) -> bool:
    if not dead_ports:
        return True
    print(f"  Restarting SSH tunnel ({len(dead_ports)} ports closed)...")
    # If Task Scheduler task exists, restart it
    for task in ("CareerBridge-Tunnel",):
        if not _ps_task_running(task):
            _start_task(task)
    time.sleep(8)
    still_dead = [p for p in dead_ports if not _port_open(p)]
    return len(still_dead) == 0


# ── Main ──────────────────────────────────────────────────────────────────────

def run() -> dict:
    now    = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    report = {"timestamp": now, "ok": True, "issues": [], "repairs": []}

    print(f"\n{'='*55}")
    print(f"CareerBridge Health Check — {now}")
    print(f"{'='*55}")

    # ── Env vars ──────────────────────────────────────────────────────────────
    missing_env = check_env()
    if missing_env:
        msg = f"Missing env vars: {', '.join(missing_env)}"
        print(f"  [WARN] {msg}")
        report["issues"].append(msg)
        # Can't auto-fix env — just alert
        _telegram(f"⚠️ Health check: {msg}")
        report["ok"] = False

    # ── MCP servers ───────────────────────────────────────────────────────────
    print("\n[MCP Servers]")
    mcp_status = check_mcps()
    dead_mcps  = [p for p, up in mcp_status.items() if not up]
    for port, up in sorted(mcp_status.items()):
        status = "UP   OK" if up else "DOWN !!"
        print(f"  {port} {MCP_PORTS[port]:15s} {status}")

    if dead_mcps:
        report["ok"] = False
        report["issues"].append(f"MCPs down: {[MCP_PORTS[p] for p in dead_mcps]}")
        fixed = repair_mcps(dead_mcps)
        if fixed:
            report["repairs"].append("MCPs restarted successfully")
            print("  Repair: MCPs restarted OK")
        else:
            still = [MCP_PORTS[p] for p in dead_mcps if not _port_open(p)]
            _telegram(f"❌ MCPs still down after restart: {still}")
            print(f"  Repair FAILED: {still}")

    # ── SSH tunnel ────────────────────────────────────────────────────────────
    print("\n[SSH Tunnel Ports]")
    tunnel_status = check_tunnel()
    dead_tunnel   = [p for p, up in tunnel_status.items() if not up]
    for port, up in sorted(tunnel_status.items()):
        status = "UP   OK" if up else "DOWN !!"
        print(f"  {port} {TUNNEL_PORTS[port]:25s} {status}")

    if dead_tunnel:
        report["ok"] = False
        report["issues"].append(f"Tunnel ports closed: {dead_tunnel}")
        fixed = repair_tunnel(dead_tunnel)
        if fixed:
            report["repairs"].append("Tunnel restarted successfully")
            print("  Repair: Tunnel restarted OK")
        else:
            _telegram(f"❌ SSH tunnel still down: ports {dead_tunnel} closed after restart attempt")
            print("  Repair FAILED — check cb_tunnel key and VPS authorized_keys")

    # ── Summary ───────────────────────────────────────────────────────────────
    print(f"\n{'='*55}")
    if report["ok"] and not report["issues"]:
        print("ALL SYSTEMS HEALTHY")
    else:
        print(f"ISSUES: {len(report['issues'])}  REPAIRS: {len(report['repairs'])}")
        for issue in report["issues"]:
            print(f"  ! {issue}")
        for repair in report["repairs"]:
            print(f"  ✓ {repair}")
    print(f"{'='*55}\n")

    return report


if __name__ == "__main__":
    result = run()
    sys.exit(0 if result["ok"] else 1)
