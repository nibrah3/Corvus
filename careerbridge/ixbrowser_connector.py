"""
IXBrowser CDP connection router.

Paid accounts (tomoneshaa@gmail.com + IXBROWSER_PAID_EMAILS env):
    IXBrowser local API at port 53200 → ix_open_profile() returns CDP URL directly.

Free accounts (everyone else):
    psutil scans running Chromium subprocesses for --remote-debugging-port=N.
    One-time setup: add --remote-debugging-port=9222 to the IXBrowser profile's
    Custom Arguments field (Settings → Profile → Advanced Args) before starting it.
"""
from __future__ import annotations

import json
import os
import time
import urllib.request
from typing import Optional

# Paid account emails — extend via IXBROWSER_PAID_EMAILS env var (comma-separated)
_PAID_EMAILS: set[str] = {"tomoneshaa@gmail.com"}
_extra = os.environ.get("IXBROWSER_PAID_EMAILS", "")
if _extra:
    _PAID_EMAILS.update(e.strip().lower() for e in _extra.split(",") if e.strip())

_IX_API        = "http://127.0.0.1:53200/api/v2"
_OPEN_TIMEOUT  = 60   # seconds; proxy cold-start can take ~10 s
_CLOSE_TIMEOUT = 30


def is_paid_account(email: str) -> bool:
    """Return True if this email has a paid IXBrowser account with local API access."""
    return (email or "").lower().strip() in _PAID_EMAILS


# ── Shared helper ──────────────────────────────────────────────────────────────

def _ix_post(endpoint: str, params: dict, timeout: int = 30) -> dict:
    import requests as _req
    r = _req.post(f"{_IX_API}/{endpoint}", json=params, timeout=timeout)
    return r.json()


# ── Paid path ─────────────────────────────────────────────────────────────────

def ix_open_profile(ix_profile_id: int) -> str:
    """
    Open an IXBrowser profile via the local API (paid accounts only).
    Retries on transient cloud-sync errors. Returns the ws:// CDP URL.
    """
    params = {
        "profile_id": ix_profile_id,
        "load_extensions": False,
        "load_profile_info_page": False,
        "cookies_backup": False,
        "args": ["--disable-extension-welcome-page", "--no-first-run"],
    }
    resp: dict = {}
    for attempt in range(6):
        resp = _ix_post("profile-open", params, timeout=_OPEN_TIMEOUT)
        err  = resp.get("error", {})
        code = err.get("code", -1)
        msg  = err.get("message", "")
        if code == 0:
            break
        if "backup" in msg.lower() or "being" in msg.lower():
            wait = 5 * (attempt + 1)
            time.sleep(wait)
            continue
        raise RuntimeError(f"IXBrowser open_profile failed (id={ix_profile_id}): {msg}")
    else:
        raise RuntimeError(f"IXBrowser profile {ix_profile_id} still syncing after retries.")

    data = resp.get("data", {})
    cdp  = data.get("ws") or data.get("cdp_url") or data.get("debugging_address")
    if not cdp:
        raise RuntimeError(f"No CDP URL in IXBrowser response: {data}")
    return cdp if cdp.startswith(("ws://", "http://")) else f"ws://{cdp}"


def ix_close_profile(ix_profile_id: int) -> None:
    """Close an IXBrowser profile via the local API (non-fatal on error)."""
    try:
        # cookies_backup=False avoids triggering a cloud sync that blocks reopening
        _ix_post("profile-close",
                 {"profile_id": int(ix_profile_id), "cookies_backup": False},
                 timeout=_CLOSE_TIMEOUT)
    except Exception:
        pass


# ── Free path ─────────────────────────────────────────────────────────────────

def _cdp_url_from_port(port: int) -> str:
    """Given a remote-debugging port, return the ws:// URL of the first open page."""
    req = urllib.request.Request(
        f"http://127.0.0.1:{port}/json",
        headers={"User-Agent": "CareerBridge-CDP/1.0"},
    )
    with urllib.request.urlopen(req, timeout=3) as r:
        targets = json.loads(r.read())
    pages = [t for t in targets if t.get("type") == "page"]
    if not pages:
        raise RuntimeError(f"No open pages on CDP port {port}")
    return pages[0]["webSocketDebuggerUrl"]


def _open_via_psutil() -> str:
    """
    Free-account path: find the Chromium subprocess launched by IXBrowser using
    psutil (scans --remote-debugging-port=N in process cmdline), then return
    the ws:// URL of the first open page on that port.
    """
    import sys as _sys
    import os as _os
    _cb = _os.path.normpath(_os.path.join(_os.path.dirname(__file__), ".."))
    if _cb not in _sys.path:
        _sys.path.insert(0, _cb)
    from careerbridge.cdp_executor import discover_cdp_port
    port = discover_cdp_port()
    return _cdp_url_from_port(port)


# ── Unified entry point ───────────────────────────────────────────────────────

def get_cdp_url(
    user_email: Optional[str] = None,
    ix_profile_id: Optional[int] = None,
) -> str:
    """
    Return a ws:// CDP URL for the active IXBrowser session.

    Paid accounts: calls ix_open_profile() via the local API at port 53200.
                   ix_profile_id must be supplied.
    Free accounts: psutil-scans the already-running Chromium subprocess for its
                   --remote-debugging-port flag, then returns its page URL.
    """
    if is_paid_account(user_email or ""):
        if ix_profile_id is None:
            raise ValueError(
                f"ix_profile_id required for paid account {user_email!r}. "
                "Resolve it with ix_find_profile() or ensure_ixbrowser_profile() first."
            )
        return ix_open_profile(ix_profile_id)
    return _open_via_psutil()
