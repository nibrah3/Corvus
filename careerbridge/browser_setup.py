"""
browser_setup.py — Visual setup: open an ixBrowser profile and navigate to a URL.

Usage:
    python browser_setup.py --profile corvus --url https://... [--wait SECONDS]

Exits 0 with JSON: {"status": "ready", "window_title": "..."}
Exits 1 with JSON: {"error": "..."}

Flow:
  1. Focus ixBrowser management window
  2. Scroll to top of profile list so the first profile is visible
  3. Find profile row by name via pywinauto UIA
  4. Click the Open button on the same row
  5. Wait for new browser window
  6. Ctrl+L → type URL → Enter → wait for page
"""
from __future__ import annotations

import argparse
import json
import sys
import time

import pyautogui
import pygetwindow as gw
import pywinauto

_IX_TITLE  = "ixBrowser"
_POLL_S    = 0.5
_SETTLE_S  = 2.0
_ROW_PX    = 80   # approximate row height in px — used for same-row matching


# ── ixBrowser window helpers ──────────────────────────────────────────────────

def _get_ix_window():
    wins = [w for w in gw.getAllWindows() if _IX_TITLE in w.title]
    return wins[0] if wins else None


def _focus_ix_window() -> bool:
    win = _get_ix_window()
    if win is None:
        return False
    try:
        win.activate()
        time.sleep(0.5)
    except Exception:
        pass
    return True


def _scroll_to_top() -> None:
    """Scroll the profile list to the top so the first profile is visible."""
    win = _get_ix_window()
    if win is None:
        return
    # Click centre of the profile list area then Home key
    cx = win.left + win.width // 2
    cy = win.top + 400  # middle of list area
    pyautogui.moveTo(cx, cy, duration=0.2)
    pyautogui.click()
    time.sleep(0.2)
    pyautogui.hotkey("ctrl", "Home")
    time.sleep(0.4)


# ── UIA profile search ────────────────────────────────────────────────────────

def _find_profile_and_open(profile_name: str) -> bool:
    """
    Use pywinauto to find the profile row and click its Open button.
    Returns True on success.
    """
    try:
        app = pywinauto.Application(backend="uia").connect(
            title_re=f"(?i).*{_IX_TITLE}.*", timeout=5
        )
        win = app.top_window()
    except Exception as e:
        raise RuntimeError(f"Cannot connect to ixBrowser window: {e}")

    # Walk all descendants and collect text + position
    try:
        descendants = win.descendants()
    except Exception as e:
        raise RuntimeError(f"Cannot query ixBrowser UI elements: {e}")

    # Find the element whose text matches the profile name
    profile_elem = None
    for ctrl in descendants:
        try:
            name = (ctrl.element_info.name or "").strip()
            if profile_name.lower() in name.lower() and name:
                rect = ctrl.element_info.rectangle
                if rect.right > rect.left and rect.bottom > rect.top:
                    profile_elem = ctrl
                    break
        except Exception:
            continue

    if profile_elem is None:
        return False

    profile_cy = (profile_elem.element_info.rectangle.top +
                  profile_elem.element_info.rectangle.bottom) // 2

    # Find an Open button on the same row (within _ROW_PX vertically)
    open_btn = None
    for ctrl in descendants:
        try:
            name = (ctrl.element_info.name or "").strip()
            ctrl_type = (ctrl.element_info.control_type or "").lower()
            if name.lower() == "open" and "button" in ctrl_type:
                rect = ctrl.element_info.rectangle
                btn_cy = (rect.top + rect.bottom) // 2
                if abs(btn_cy - profile_cy) <= _ROW_PX:
                    open_btn = ctrl
                    break
        except Exception:
            continue

    if open_btn is None:
        # Fallback: click the profile name itself (double-click may open)
        r = profile_elem.element_info.rectangle
        cx = (r.left + r.right) // 2
        cy = (r.top + r.bottom) // 2
        pyautogui.moveTo(cx, cy, duration=0.25)
        pyautogui.doubleClick()
    else:
        r = open_btn.element_info.rectangle
        cx = (r.left + r.right) // 2
        cy = (r.top + r.bottom) // 2
        pyautogui.moveTo(cx, cy, duration=0.25)
        time.sleep(0.15)
        pyautogui.click()

    return True


# ── New window detection ──────────────────────────────────────────────────────

def _snapshot_windows() -> frozenset[str]:
    return frozenset(w.title for w in gw.getAllWindows() if w.title.strip())


def _wait_new_window(before: frozenset[str], timeout: int) -> gw.Win32Window | None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        time.sleep(_POLL_S)
        current = frozenset(w.title for w in gw.getAllWindows() if w.title.strip())
        for title in current - before:
            if title and _IX_TITLE.lower() not in title.lower():
                wins = gw.getWindowsWithTitle(title)
                if wins:
                    return wins[0]
        # Also accept ixBrowser-titled windows that appeared (profile may keep title)
        for title in current - before:
            if title:
                wins = gw.getWindowsWithTitle(title)
                if wins:
                    return wins[0]
    return None


# ── Main setup flow ───────────────────────────────────────────────────────────

def setup(profile_name: str, url: str, wait: int = 20) -> dict:
    # Step 1: focus ixBrowser
    if not _focus_ix_window():
        return {"error": "ixBrowser window not found — is it running?"}

    # Step 2: scroll list to top so first profile is visible
    _scroll_to_top()

    # Step 3: snapshot, find profile, click Open
    before = _snapshot_windows()
    try:
        found = _find_profile_and_open(profile_name)
    except RuntimeError as e:
        return {"error": str(e)}

    if not found:
        return {"error": f"Profile '{profile_name}' not found in ixBrowser profile list"}

    # Step 4: wait for browser window
    new_win = _wait_new_window(before, timeout=wait)
    if new_win is None:
        return {"error": f"No browser window appeared after opening profile '{profile_name}'"}

    try:
        new_win.activate()
    except Exception:
        pass
    time.sleep(_SETTLE_S)

    # Step 5: navigate to URL
    pyautogui.hotkey("ctrl", "l")
    time.sleep(0.4)
    pyautogui.hotkey("ctrl", "a")
    time.sleep(0.1)
    pyautogui.typewrite(url, interval=0.04)
    pyautogui.press("enter")
    time.sleep(3)

    return {"status": "ready", "window_title": new_win.title}


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--profile", required=True)
    parser.add_argument("--url",     required=True)
    parser.add_argument("--wait",    type=int, default=20)
    args = parser.parse_args()

    result = setup(profile_name=args.profile, url=args.url, wait=args.wait)
    json.dump(result, sys.stdout)
    sys.stdout.write("\n")
    sys.exit(1 if "error" in result else 0)


if __name__ == "__main__":
    main()
