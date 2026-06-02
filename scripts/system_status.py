#!/usr/bin/env python3
"""
system_status.py
Checks all local MCP service ports and VPS tunnel ports.
Prints a single JSON object to stdout for Claude to read and report.
"""
import json
import socket
import sys

MCP_PORTS = {
    8701: "Humanizer",
    8702: "Screen Capture",
    8703: "Windows UI",
    8704: "Browser Control",
    8705: "Gemini Vision",
    8706: "Telegram",
    8707: "Persona & Answers",
    8708: "Database",
    8709: "Memory",
    8710: "DOM Reader",
    8712: "CDP Bridge",
    8713: "VPS Bridge",
    8714: "Schools",
}

TUNNEL_PORTS = {
    6380: "VPS Redis",
    5433: "VPS Database",
    3101: "VPS Crawlee",
    7788: "VPS Firecrawl",
}


def _up(port: int, timeout: float = 1.0) -> bool:
    try:
        with socket.create_connection(("127.0.0.1", port), timeout=timeout):
            return True
    except Exception:
        return False


mcp_status = {name: ("ok" if _up(port) else "offline") for port, name in MCP_PORTS.items()}
tunnel_status = {name: ("ok" if _up(port) else "offline") for port, name in TUNNEL_PORTS.items()}

mcp_ok    = sum(1 for s in mcp_status.values() if s == "ok")
tunnel_ok = sum(1 for s in tunnel_status.values() if s == "ok")

print(json.dumps({
    "mcp_services":  mcp_status,
    "mcp_ok":        mcp_ok,
    "mcp_total":     len(mcp_status),
    "tunnel":        tunnel_status,
    "tunnel_ok":     tunnel_ok,
    "tunnel_total":  len(tunnel_status),
}, indent=2))
