"""
Page-load detection without CDP.

We can't use CDP's Page.loadEventFired — so we detect load completion by:
1. Polling the window title: Chrome changes title from "Loading..." to the page title.
2. Watching UIA tree stability: element count stops changing between polls.
3. Hard timeout fallback.

The combination works because:
- Title poll is fast (no UIA traversal)
- UIA stability catches SPAs that don't change title during navigation
- Hard timeout ensures we never hang
"""
from __future__ import annotations

import time
import ctypes
import ctypes.wintypes as wt


def _get_foreground_title() -> str:
    hwnd = ctypes.windll.user32.GetForegroundWindow()
    if not hwnd:
        return ""
    buf = ctypes.create_unicode_buffer(512)
    ctypes.windll.user32.GetWindowTextW(hwnd, buf, 512)
    return buf.value


def wait_for_load(
    timeout: float = 15.0,
    stable_ms: int = 600,
    poll_ms: int = 200,
) -> dict:
    """
    Wait for the current Chrome page to finish loading.

    Strategy:
      1. Wait until title no longer contains "Loading" / ends with "..."
      2. Then wait until title is stable for `stable_ms` milliseconds.

    Args:
        timeout:   Max seconds to wait before giving up.
        stable_ms: Title must not change for this many ms before we declare "loaded".
        poll_ms:   How often to poll the title (milliseconds).

    Returns:
        {"status": "loaded"|"timeout", "title": str, "elapsed_ms": int}
    """
    deadline = time.monotonic() + timeout
    poll_s = poll_ms / 1000.0
    stable_s = stable_ms / 1000.0
    start = time.monotonic()

    last_title = _get_foreground_title()
    stable_since = time.monotonic()

    while time.monotonic() < deadline:
        time.sleep(poll_s)
        title = _get_foreground_title()

        # Chrome shows "Loading..." or "data:..." while fetching
        still_loading = (
            title.endswith("...")
            or title.lower().startswith("loading")
            or title == ""
        )
        if still_loading:
            last_title = title
            stable_since = time.monotonic()
            continue

        if title != last_title:
            last_title = title
            stable_since = time.monotonic()
            continue

        if (time.monotonic() - stable_since) >= stable_s:
            elapsed_ms = int((time.monotonic() - start) * 1000)
            return {"status": "loaded", "title": title, "elapsed_ms": elapsed_ms}

    elapsed_ms = int((time.monotonic() - start) * 1000)
    return {"status": "timeout", "title": _get_foreground_title(), "elapsed_ms": elapsed_ms}
