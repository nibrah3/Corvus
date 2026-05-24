"""
ixbrowser_launcher.py — Unified IXBrowser launcher.

Single responsibility: ensure IXBrowser is running AND a specific profile is
open, then return the CDP URL — without any manual UI interaction required.

Routing by account type:
  Paid (tomoneshaa + IXBROWSER_PAID_EMAILS):
    Uses the IXBrowser local REST API at port 53200. Programmatic, instant.

  Free (everyone else):
    1. Launches IXBrowser.exe if not running (subprocess + process check).
    2. Opens the named profile via pywinauto UIA automation on the IXBrowser
       management window — no human clicks needed.
    3. Polls for CDP port via psutil process scan.

Usage (CLI):
    python scripts/ixbrowser_launcher.py --profile <postgres_profile_id>
                                         --email <user_email>
                                         [--ix-profile-id <int>]
                                         [--wait <seconds>]

Usage (API):
    from scripts.ixbrowser_launcher import launch_and_get_cdp_url
    cdp_url = launch_and_get_cdp_url("james-okafor", "user@email.com")
"""
from __future__ import annotations

import argparse
import json
import logging
import os
import subprocess
import sys
import time
from pathlib import Path
from typing import Optional

CB_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(CB_DIR))

from careerbridge.ixbrowser_connector import (
    get_cdp_url,
    is_paid_account,
    ix_open_profile,
)

log = logging.getLogger(__name__)

# ── IXBrowser exe discovery ───────────────────────────────────────────────────

def _find_ixbrowser_exe() -> Optional[str]:
    explicit = os.environ.get("IXBROWSER_EXE_PATH", "")
    if explicit and os.path.isfile(explicit):
        return explicit

    candidates = [
        r"C:\Users\Mike\AppData\Roaming\ixBrowser-Resources\synchronizer\ixBrowser.exe",
        r"C:\Program Files\IXBrowser\IXBrowser.exe",
        r"C:\Program Files (x86)\IXBrowser\IXBrowser.exe",
        os.path.expanduser(r"~\AppData\Local\IXBrowser\IXBrowser.exe"),
        os.path.expanduser(r"~\AppData\Roaming\ixBrowser-Resources\synchronizer\ixBrowser.exe"),
        os.path.expanduser(r"~\AppData\Local\Programs\IXBrowser\IXBrowser.exe"),
    ]
    for p in candidates:
        if os.path.isfile(p):
            return p

    try:
        import winreg
        for hive, key in [
            (winreg.HKEY_CURRENT_USER,  r"Software\IXBrowser"),
            (winreg.HKEY_LOCAL_MACHINE, r"Software\IXBrowser"),
        ]:
            try:
                with winreg.OpenKey(hive, key) as k:
                    exe, _ = winreg.QueryValueEx(k, "InstallPath")
                    cand = os.path.join(str(exe), "IXBrowser.exe")
                    if os.path.isfile(cand):
                        return cand
            except Exception:
                pass
    except ImportError:
        pass
    return None


def _ixbrowser_process_running() -> bool:
    """Return True if IXBrowser.exe process is alive."""
    try:
        result = subprocess.run(
            ["tasklist", "/FI", "IMAGENAME eq ixBrowser.exe", "/NH", "/FO", "CSV"],
            capture_output=True, text=True, timeout=5,
        )
        return "ixbrowser.exe" in result.stdout.lower()
    except Exception:
        return False


def _api_port_up() -> bool:
    import socket
    try:
        with socket.create_connection(("127.0.0.1", 53200), timeout=2):
            return True
    except Exception:
        return False


def _launch_ixbrowser_exe(wait_s: int = 20) -> bool:
    """Launch IXBrowser.exe and wait for the process to appear. Returns True on success."""
    exe = _find_ixbrowser_exe()
    if not exe:
        raise RuntimeError(
            "IXBrowser.exe not found. Set IXBROWSER_EXE_PATH in D:\\cb-core\\.env "
            "or install IXBrowser."
        )

    log.info("Launching IXBrowser from %s", exe)
    flags = subprocess.CREATE_NEW_PROCESS_GROUP
    try:
        subprocess.Popen(
            [exe],
            cwd=os.path.dirname(exe),
            creationflags=flags,
            close_fds=True,
        )
    except Exception as e:
        log.warning("Popen failed (%s), trying shell=True", e)
        subprocess.Popen(exe, shell=True)

    deadline = time.monotonic() + wait_s
    while time.monotonic() < deadline:
        if _ixbrowser_process_running():
            time.sleep(2)   # let main window initialise
            return True
        time.sleep(1)
    return False


# ── Free-account: UI-automation profile opener ────────────────────────────────

def _open_profile_via_uia(profile_name: str, wait_s: int = 30) -> bool:
    """
    Use pywinauto UIA automation to click the Open button for the named profile
    in the IXBrowser management window. No human interaction required.
    Returns True if a new browser window appeared.
    """
    try:
        import pywinauto
        import pygetwindow as gw
    except ImportError:
        raise RuntimeError("pywinauto and pygetwindow required: pip install pywinauto pygetwindow")

    # Wait for IXBrowser management window
    deadline = time.monotonic() + 15
    app = None
    while time.monotonic() < deadline:
        try:
            app = pywinauto.Application(backend="uia").connect(
                title_re=r"(?i).*ixBrowser.*", timeout=2
            )
            break
        except Exception:
            time.sleep(1)

    if app is None:
        raise RuntimeError("IXBrowser management window not found after launch.")

    win = app.top_window()

    # Scroll profile list to top
    try:
        win.type_keys("{CTRL}{HOME}", set_foreground=True)
        time.sleep(0.4)
    except Exception:
        pass

    # Find profile row by name
    profile_elem = None
    for ctrl in win.descendants():
        try:
            name = (ctrl.element_info.name or "").strip()
            if profile_name.lower() in name.lower() and name:
                r = ctrl.element_info.rectangle
                if r.right > r.left and r.bottom > r.top:
                    profile_elem = ctrl
                    break
        except Exception:
            continue

    if profile_elem is None:
        raise RuntimeError(
            f"Profile '{profile_name}' not found in IXBrowser profile list."
        )

    profile_cy = (
        profile_elem.element_info.rectangle.top
        + profile_elem.element_info.rectangle.bottom
    ) // 2

    ROW_PX = 80
    open_btn = None
    for ctrl in win.descendants():
        try:
            n   = (ctrl.element_info.name or "").strip()
            ct  = (ctrl.element_info.control_type or "").lower()
            if n.lower() == "open" and "button" in ct:
                r  = ctrl.element_info.rectangle
                cy = (r.top + r.bottom) // 2
                if abs(cy - profile_cy) <= ROW_PX:
                    open_btn = ctrl
                    break
        except Exception:
            continue

    # Record existing windows before opening
    before = frozenset(w.title for w in gw.getAllWindows() if w.title.strip())

    if open_btn is not None:
        open_btn.click_input()
    else:
        # Fallback: double-click the profile name
        profile_elem.double_click_input()

    # Wait for new browser window
    deadline = time.monotonic() + wait_s
    while time.monotonic() < deadline:
        current = frozenset(w.title for w in gw.getAllWindows() if w.title.strip())
        new = current - before
        if new:
            log.info("Browser window opened: %s", list(new)[0])
            time.sleep(1.5)  # settle
            return True
        time.sleep(0.5)

    log.warning("No new browser window appeared after opening profile '%s'", profile_name)
    return False


# ── Unified entry point ───────────────────────────────────────────────────────

def launch_and_get_cdp_url(
    postgres_profile_id: str,
    user_email: str,
    ix_profile_id: Optional[int] = None,
    wait_s: int = 45,
) -> str:
    """
    Ensure IXBrowser is running, open the specified profile, and return a
    ws:// CDP URL ready for CDPExecutor or browser-use to attach to.

    Paid accounts: uses IXBrowser local API — no window management needed.
    Free accounts: launches IXBrowser.exe if needed, opens profile via pywinauto.
    """
    if is_paid_account(user_email):
        # Paid path: API does everything
        if not _api_port_up():
            log.info("IXBrowser API not running — launching exe...")
            if not _launch_ixbrowser_exe(wait_s=wait_s):
                raise RuntimeError("IXBrowser failed to start within timeout.")
            # Wait for API port
            deadline = time.monotonic() + 20
            while time.monotonic() < deadline:
                if _api_port_up():
                    break
                time.sleep(1)
            else:
                raise RuntimeError("IXBrowser started but API port 53200 not up.")

        if ix_profile_id is None:
            raise ValueError(
                f"ix_profile_id is required for paid account {user_email!r}. "
                "Resolve it with ix_find_profile() or ensure_ixbrowser_profile() first."
            )
        return ix_open_profile(ix_profile_id)

    else:
        # Free path: launch exe if not running, then open profile via UIA
        if not _ixbrowser_process_running():
            log.info("IXBrowser not running — launching...")
            if not _launch_ixbrowser_exe(wait_s=wait_s):
                raise RuntimeError("IXBrowser failed to start within timeout.")
            time.sleep(3)  # let main UI fully render

        log.info("Opening profile '%s' via UIA automation...", postgres_profile_id)
        _open_profile_via_uia(postgres_profile_id, wait_s=wait_s)

        # Discover CDP port via psutil now that profile is open
        return get_cdp_url(user_email=user_email)


# ── CLI ───────────────────────────────────────────────────────────────────────

def main() -> None:
    logging.basicConfig(level=logging.INFO,
                        format="%(asctime)s %(levelname)s %(message)s")
    parser = argparse.ArgumentParser(
        description="Launch IXBrowser + open profile → print CDP URL"
    )
    parser.add_argument("--profile",        required=True, help="Postgres profile ID or profile name")
    parser.add_argument("--email",          required=True, help="Candidate email (determines paid/free path)")
    parser.add_argument("--ix-profile-id",  type=int,      help="IXBrowser numeric profile ID (paid accounts)")
    parser.add_argument("--wait",           type=int, default=45, help="Max seconds to wait for browser")
    args = parser.parse_args()

    try:
        cdp_url = launch_and_get_cdp_url(
            postgres_profile_id=args.profile,
            user_email=args.email,
            ix_profile_id=args.ix_profile_id,
            wait_s=args.wait,
        )
        print(json.dumps({"status": "ready", "cdp_url": cdp_url}))
    except Exception as e:
        print(json.dumps({"status": "error", "error": str(e)}))
        sys.exit(1)


if __name__ == "__main__":
    main()
