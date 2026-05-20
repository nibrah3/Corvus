"""
Chrome process manager — launch / attach to Chrome without CDP.

Why no CDP:
  Chrome DevTools Protocol is detectable by assessment platforms (listening port,
  --remote-debugging-port flag in process cmdline, special DevTools cookies).
  We drive Chrome purely via OS-level keyboard/mouse through the humanizer.

Launch flags we use:
  --force-renderer-accessibility  Exposes all DOM elements through UIA tree.
                                  Without this, Chrome shows only 3 native controls.
  --no-first-run                  Skip welcome/consent dialogs.
  --disable-features=Translate    Suppress translation bar (changes page layout).
  --start-maximized               Consistent window geometry.

We do NOT use:
  --remote-debugging-port         CDP — detectable
  --disable-extensions            Would kill legitimate extensions user may need
  --headless                      Requires CDP or Selenium; detectable
"""
from __future__ import annotations

import subprocess
import time
import ctypes
import ctypes.wintypes as wt
from pathlib import Path

_CHROME_PATHS = [
    r"C:\Program Files\Google\Chrome\Application\chrome.exe",
    r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
]

_LAUNCH_FLAGS = [
    "--force-renderer-accessibility",
    "--no-first-run",
    "--disable-features=Translate",
    "--start-maximized",
]


def _find_chrome() -> str:
    for p in _CHROME_PATHS:
        if Path(p).exists():
            return p
    raise FileNotFoundError(
        "Chrome not found at default paths. "
        "Set CHROME_PATH env var or pass chrome_path to launch_chrome()."
    )


def launch_chrome(url: str = "", chrome_path: str = "") -> dict:
    """
    Launch Chrome with accessibility flags. Returns process info.

    Args:
        url:         URL to open. Empty = new tab.
        chrome_path: Override Chrome executable path.

    Returns:
        {pid, chrome_path, url, launched_at}
    """
    import os
    exe = chrome_path or os.environ.get("CHROME_PATH", "") or _find_chrome()
    cmd = [exe] + _LAUNCH_FLAGS
    if url:
        cmd.append(url)

    proc = subprocess.Popen(cmd, creationflags=subprocess.DETACHED_PROCESS)
    time.sleep(1.5)  # give Chrome time to open its window

    return {
        "pid":          proc.pid,
        "chrome_path":  exe,
        "url":          url,
        "launched_at":  time.strftime("%H:%M:%S"),
    }


def get_chrome_hwnd() -> int | None:
    """Return HWND of the frontmost Chrome window, or None."""
    found: list[int] = []

    @ctypes.WINFUNCTYPE(ctypes.c_bool, wt.HWND, wt.LPARAM)
    def _cb(hwnd, _lparam):
        buf = ctypes.create_unicode_buffer(256)
        ctypes.windll.user32.GetClassNameW(hwnd, buf, 256)
        if buf.value == "Chrome_WidgetWin_1":
            title_buf = ctypes.create_unicode_buffer(512)
            ctypes.windll.user32.GetWindowTextW(hwnd, title_buf, 512)
            title = title_buf.value
            # Skip extension popups, devtools, etc.
            if title and "Google Chrome" not in title or "- Google Chrome" in title:
                found.append(hwnd)
        return True

    ctypes.windll.user32.EnumWindows(_cb, 0)
    return found[0] if found else None


def focus_chrome() -> bool:
    """Bring Chrome to foreground. Returns True if a Chrome window was found."""
    hwnd = get_chrome_hwnd()
    if not hwnd:
        return False
    ctypes.windll.user32.SetForegroundWindow(hwnd)
    time.sleep(0.1)
    return True
