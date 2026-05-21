"""
DOM MCP server — port 8710.

Exposes live browser DOM context to Claude via four tools:
  get_page_context   — full snapshot (top frame + merged iframes)
  get_form_elements  — inputs + questions only (fast path for answer selection)
  wait_for_update    — block until extension reports a DOM change
  list_tabs          — show all known open tabs (useful for multi-window sessions)

The CB DOM Relay extension POSTs snapshots to port 8711 (_receiver).
This server reads from the shared DomStore and serves Claude via port 8710 (MCP HTTP).
"""
from __future__ import annotations

import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from _minmcp import MinMCP
from ._store import DomStore
from ._receiver import start_receiver

_store = DomStore()
start_receiver(_store, port=8711)

mcp = MinMCP("dom")


@mcp.tool()
def get_page_context() -> dict:
    """
    Return the active tab's full DOM snapshot: URL, title, questions, radio groups,
    inputs, buttons, passage text, and any iframe content merged in.

    Use when first landing on a page to understand its full structure.
    Falls back gracefully when the extension hasn't relayed yet.
    """
    data = _store.get()
    if not data:
        return {
            "error": "No DOM data yet. Is the CB DOM Relay extension loaded and active? "
                     "Switch to the target tab to trigger a relay."
        }
    return data


@mcp.tool()
def get_form_elements() -> dict:
    """
    Return only the question text, radio groups, and non-radio inputs from the active tab.

    Lighter than get_page_context — use when you just need the question and answer options.
    Iframes are included if they contain form elements.
    """
    data = _store.get()
    if not data:
        return {"error": "No DOM data yet."}

    result = {
        "url":          data.get("url"),
        "questions":    data.get("questions", []),
        "radio_groups": data.get("radio_groups", []),
        "inputs":       [i for i in data.get("inputs", []) if i.get("type") not in ("radio", "checkbox")],
    }

    # Include iframe form elements if present
    for frame in data.get("iframes", []):
        if frame.get("radio_groups") or frame.get("inputs") or frame.get("questions"):
            result.setdefault("iframes", []).append({
                "url":          frame.get("url"),
                "questions":    frame.get("questions", []),
                "radio_groups": frame.get("radio_groups", []),
                "inputs":       [i for i in frame.get("inputs", []) if i.get("type") not in ("radio", "checkbox")],
            })

    return result


@mcp.tool()
def wait_for_update(timeout_ms: int = 6000) -> dict:
    """
    Block until the extension reports a DOM change, then return the updated context.

    Call immediately after clicking Next / Submit / Continue so Claude waits for the
    new question to load. Falls back to the last known snapshot on timeout.

    Args:
        timeout_ms: Maximum wait in milliseconds (default 6000).
    """
    data = _store.wait_for_update(timeout=timeout_ms / 1000)
    if not data:
        return {"error": "Timed out waiting for DOM update."}
    return data


@mcp.tool()
def list_tabs() -> list:
    """
    List all browser tabs currently known to the DOM relay.

    Use to verify which tabs are active and sending data, or to debug
    multi-window sessions where the wrong tab may be relaying.
    """
    tabs = _store.active_tabs()
    if not tabs:
        return [{"info": "No tabs known yet. Switch to a tab with the extension active."}]
    return tabs


if __name__ == "__main__":
    mcp.run()
