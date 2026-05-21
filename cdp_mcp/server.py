# cdp_mcp/server.py — CDP MCP server (port 8712)
# Exposes ixBrowser CDP control to Claude Code as MCP tools.
# Backup execution layer: use when OS-level automation faces anti-bot friction.
#
# Tools:
#   cdp_connect       — discover ixBrowser port and attach
#   cdp_disconnect    — release WebSocket connection
#   cdp_ping          — check if connection is live
#   cdp_get_axtree    — full accessibility tree of the active page
#   cdp_click         — click element by CSS selector
#   cdp_click_js      — click element returned by JS expression
#   cdp_type          — type text with Gaussian keystroke jitter
#   cdp_scroll        — scroll page up/down
#   cdp_eval          — evaluate arbitrary JS and return result
#   cdp_page_info     — current page URL and title

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

import json
from typing import Optional

from _minmcp import MinMCP
from careerbridge.cdp_executor import CDPExecutor, CDPError

mcp      = MinMCP("cdp-mcp")
_executor: Optional[CDPExecutor] = None


def _get_executor() -> CDPExecutor:
    global _executor
    if _executor is None:
        _executor = CDPExecutor()
    return _executor


# ── Connection ────────────────────────────────────────────────────────────────

@mcp.tool
def cdp_connect(port: int = 0) -> str:
    """
    Discover ixBrowser's remote debugging port and attach via CDP WebSocket.
    Leave port=0 to auto-discover via psutil (recommended).
    Returns the connected port number.
    """
    ex = _get_executor()
    try:
        connected_port = ex.connect(port=port if port else None)
        return json.dumps({"status": "connected", "port": connected_port})
    except CDPError as e:
        return json.dumps({"status": "error", "error": str(e)})


@mcp.tool
def cdp_disconnect() -> str:
    """Disconnect from ixBrowser CDP WebSocket."""
    global _executor
    if _executor is not None:
        _executor.disconnect()
        _executor = None
    return "disconnected"


@mcp.tool
def cdp_ping() -> str:
    """
    Check if the CDP connection to ixBrowser is live.
    Returns {"alive": true/false}.
    """
    ex = _get_executor()
    alive = ex.ping() if ex._connected else False
    return json.dumps({"alive": alive})


# ── Accessibility tree ────────────────────────────────────────────────────────

@mcp.tool
def cdp_get_axtree(roles_filter: str = "") -> str:
    """
    Return the full accessibility tree of the active page as JSON.
    Each node: {nodeId, role, name, description, value, properties, childIds}.
    roles_filter: comma-separated roles to include (e.g. "button,radio,checkbox").
    Leave empty to return all non-trivial nodes.
    """
    ex = _get_executor()
    try:
        tree = ex.get_axtree()
        if roles_filter:
            keep = {r.strip().lower() for r in roles_filter.split(",")}
            tree = [n for n in tree if n.get("role", "").lower() in keep]
        return json.dumps(tree, ensure_ascii=False)
    except CDPError as e:
        return json.dumps({"error": str(e)})


# ── Click ─────────────────────────────────────────────────────────────────────

@mcp.tool
def cdp_click(selector: str) -> str:
    """
    Click an element by CSS selector via CDP mouse events.
    Uses getBoundingClientRect to find centre, then dispatches mousePressed +
    mouseReleased with Gaussian hold-duration jitter.
    Example: cdp_click('input[type="radio"][value="Agree"]')
    """
    ex = _get_executor()
    try:
        ex.click_selector(selector)
        return json.dumps({"status": "clicked", "selector": selector})
    except CDPError as e:
        return json.dumps({"status": "error", "error": str(e)})


@mcp.tool
def cdp_click_js(js_expr: str) -> str:
    """
    Click an element returned by a JavaScript expression via CDP.
    The expression must evaluate to an Element node.
    Example: cdp_click_js('document.querySelector("button[aria-label=Submit]")')
    Example: cdp_click_js('Array.from(document.querySelectorAll("label")).find(l => l.textContent.trim() === "Strongly Agree")')
    """
    ex = _get_executor()
    try:
        ex.click_js(js_expr)
        return json.dumps({"status": "clicked"})
    except CDPError as e:
        return json.dumps({"status": "error", "error": str(e)})


# ── Typing ────────────────────────────────────────────────────────────────────

@mcp.tool
def cdp_type(text: str) -> str:
    """
    Type text into the focused element via CDP keyboard injection.
    Applies ex-Gaussian inter-key intervals for natural timing variation.
    Click the target field first with cdp_click before calling this.
    """
    ex = _get_executor()
    try:
        ex.type_text(text)
        return json.dumps({"status": "typed", "chars": len(text)})
    except CDPError as e:
        return json.dumps({"status": "error", "error": str(e)})


# ── Scroll ────────────────────────────────────────────────────────────────────

@mcp.tool
def cdp_scroll(direction: str = "down", clicks: int = 3) -> str:
    """
    Scroll the page via CDP mouse-wheel events.
    direction: "up" or "down"
    clicks: number of wheel notches (each ≈ 120px)
    """
    ex = _get_executor()
    try:
        ex.scroll(direction=direction, clicks=clicks)
        return json.dumps({"status": "scrolled", "direction": direction, "clicks": clicks})
    except CDPError as e:
        return json.dumps({"status": "error", "error": str(e)})


# ── JS evaluation ─────────────────────────────────────────────────────────────

@mcp.tool
def cdp_eval(expression: str) -> str:
    """
    Evaluate a JavaScript expression in the page context and return the result as JSON.
    Useful for reading state, querying elements, or triggering JS functions directly.
    Example: cdp_eval('document.querySelectorAll("input[type=radio]").length')
    Example: cdp_eval('window.location.href')
    """
    ex = _get_executor()
    try:
        result = ex.eval_js(expression)
        return json.dumps({"result": result})
    except CDPError as e:
        return json.dumps({"error": str(e)})


# ── Page info ─────────────────────────────────────────────────────────────────

@mcp.tool
def cdp_page_info() -> str:
    """Return the current page URL and title."""
    ex = _get_executor()
    try:
        info = ex.get_page_info()
        return json.dumps(info)
    except CDPError as e:
        return json.dumps({"error": str(e)})


if __name__ == "__main__":
    mcp.run()
