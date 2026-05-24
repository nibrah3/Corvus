"""
verify_code_injector.py — Desktop-side OTP injection.

Reads verification codes stored by corvus_imap_monitor.py (VPS daemon) from
Redis at corvus:verify:{email_address} and types them into the active browser page.

The VPS IMAP daemon does the email watching. This module only does the desktop half:
  Redis (corvus:verify:{email}) → poll → find OTP field → type code

Called from application_pipeline.py as a fire-and-forget async task:
    asyncio.ensure_future(verify_code_injector(browser_session, profile_email))

Also usable standalone from assessment_pipeline.py's CDPExecutor context:
    asyncio.ensure_future(verify_code_injector_cdp(cdp_executor, profile_email))
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
import re
import socket
import sys
import time
from typing import Optional

CB_DIR = os.path.normpath(os.path.join(os.path.dirname(__file__)))
if CB_DIR not in sys.path:
    sys.path.insert(0, CB_DIR)

log = logging.getLogger(__name__)

_REDIS_HOST = "127.0.0.1"
_REDIS_PORT = int(os.environ.get("REDIS_PORT", "6380"))  # SSH tunnel default
_POLL_INTERVAL = 3.0   # seconds between Redis checks
_TIMEOUT       = 300.0  # 5-minute window to receive a code

_OTP_ROLES = frozenset({"textbox", "searchbox", "spinbutton"})
_OTP_LABELS = frozenset({
    "verification", "verify", "code", "otp", "one-time", "token",
    "pin", "confirmation", "enter the", "6-digit", "4-digit",
})


# ── Redis helpers (raw socket, no redis-py dependency) ────────────────────────

def _redis_get(key: str) -> Optional[str]:
    try:
        with socket.create_connection((_REDIS_HOST, _REDIS_PORT), timeout=3) as s:
            cmd = f"*2\r\n$3\r\nGET\r\n${len(key)}\r\n{key}\r\n"
            s.sendall(cmd.encode())
            reply = s.recv(4096).decode(errors="replace")
            if reply.startswith("$-1") or reply.startswith("-"):
                return None
            lines = reply.split("\r\n")
            return lines[1] if len(lines) > 1 else None
    except Exception:
        return None


def _redis_del(key: str) -> None:
    try:
        with socket.create_connection((_REDIS_HOST, _REDIS_PORT), timeout=3) as s:
            cmd = f"*2\r\n$3\r\nDEL\r\n${len(key)}\r\n{key}\r\n"
            s.sendall(cmd.encode())
            s.recv(64)
    except Exception:
        pass


# ── Code extraction ───────────────────────────────────────────────────────────

def _read_code_from_redis(email: str) -> Optional[str]:
    """Return the verification code for this email if one is stored, else None."""
    key = f"corvus:verify:{email.lower()}"
    raw = _redis_get(key)
    if not raw:
        return None
    try:
        data = json.loads(raw)
        code = data.get("code", "")
        if code and len(code) >= 4:
            log.info("OTP retrieved for %s: %s (from: %s)", email, code, data.get("from", "?")[:50])
            return code
    except json.JSONDecodeError:
        # Plain string fallback
        stripped = raw.strip()
        if re.fullmatch(r"[A-Z0-9]{4,12}", stripped, re.IGNORECASE):
            return stripped
    return None


def _consume_code(email: str) -> None:
    """Remove the Redis key after successful injection to prevent re-use."""
    _redis_del(f"corvus:verify:{email.lower()}")


# ── OTP field detection ───────────────────────────────────────────────────────

def _is_otp_field(node: dict) -> bool:
    """Return True if this accessibility node looks like an OTP input."""
    name  = (node.get("name") or "").lower()
    desc  = (node.get("description") or "").lower()
    label = (node.get("label") or "").lower()
    combined = f"{name} {desc} {label}"
    return any(kw in combined for kw in _OTP_LABELS)


# ── browser-use session variant (async) ──────────────────────────────────────

async def verify_code_injector(browser_session, profile_email: str) -> None:
    """
    Async fire-and-forget: polls Redis for OTP, types it when received.
    Designed for use with browser-use BrowserSession objects.

    The VPS IMAP daemon populates Redis; this just reads and injects.
    """
    if not profile_email:
        return

    deadline = asyncio.get_event_loop().time() + _TIMEOUT
    injected = False

    while asyncio.get_event_loop().time() < deadline and not injected:
        code = _read_code_from_redis(profile_email)
        if code:
            try:
                page = await browser_session.get_current_page()
                # Try to find an OTP-looking input field
                js = """
                (function() {
                    var inputs = document.querySelectorAll('input[type="text"], input[type="number"], input:not([type])');
                    for (var i = 0; i < inputs.length; i++) {
                        var el = inputs[i];
                        var lbl = (el.getAttribute('aria-label') || el.getAttribute('placeholder') ||
                                   el.getAttribute('name') || el.getAttribute('id') || '').toLowerCase();
                        var keywords = ['otp','code','verify','pin','token','confirmation'];
                        if (keywords.some(function(k){ return lbl.indexOf(k) !== -1; })) {
                            var r = el.getBoundingClientRect();
                            return {x: r.left + r.width/2, y: r.top + r.height/2, found: true};
                        }
                    }
                    // Fallback: first visible short text input
                    for (var j = 0; j < inputs.length; j++) {
                        var el2 = inputs[j];
                        var max = parseInt(el2.getAttribute('maxlength') || '999');
                        if (max <= 10 && !el2.disabled && !el2.readOnly) {
                            var r2 = el2.getBoundingClientRect();
                            if (r2.width > 0 && r2.height > 0)
                                return {x: r2.left + r2.width/2, y: r2.top + r2.height/2, found: true};
                        }
                    }
                    return null;
                })()
                """
                coords = await page.evaluate(js)
                if coords and coords.get("found"):
                    await page.mouse.click(coords["x"], coords["y"])
                    await asyncio.sleep(0.2)
                    await page.keyboard.type(code, delay=80)
                    await asyncio.sleep(0.3)
                    # Try pressing Enter to submit
                    await page.keyboard.press("Enter")
                    log.info("OTP injected for %s: %s", profile_email, code)
                    _consume_code(profile_email)
                    injected = True
                else:
                    log.debug("OTP ready but no matching input field found yet — will retry")
            except Exception as e:
                log.debug("OTP injection attempt failed: %s", e)

        if not injected:
            await asyncio.sleep(_POLL_INTERVAL)

    if not injected:
        log.warning("OTP injection timed out for %s (%.0fs window)", profile_email, _TIMEOUT)


# ── CDPExecutor variant (sync, for assessment_pipeline.py) ───────────────────

def verify_code_injector_cdp(cdp_executor, profile_email: str, timeout: float = _TIMEOUT) -> bool:
    """
    Sync variant: polls Redis for OTP and types it via CDPExecutor.
    Returns True if code was injected, False if timed out.

    Runs in a background thread from assessment_pipeline.py.
    """
    if not profile_email:
        return False

    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        code = _read_code_from_redis(profile_email)
        if code:
            try:
                js = """
                (function() {
                    var inputs = document.querySelectorAll('input');
                    for (var i = 0; i < inputs.length; i++) {
                        var el = inputs[i];
                        var lbl = (el.getAttribute('aria-label') || el.getAttribute('placeholder') ||
                                   el.getAttribute('name') || el.getAttribute('id') || '').toLowerCase();
                        if (['otp','code','verify','pin','token'].some(function(k){ return lbl.indexOf(k)!==-1; })) {
                            el.focus();
                            el.value = arguments[0];
                            el.dispatchEvent(new Event('input', {bubbles:true}));
                            el.dispatchEvent(new Event('change', {bubbles:true}));
                            return true;
                        }
                    }
                    return false;
                })()
                """
                result = cdp_executor.eval_js(f"({js})({json.dumps(code)})")
                if result:
                    log.info("OTP injected via CDP for %s: %s", profile_email, code)
                    _consume_code(profile_email)
                    return True
                log.debug("OTP ready but CDP field injection returned false — retrying")
            except Exception as e:
                log.debug("CDP OTP injection failed: %s", e)

        time.sleep(_POLL_INTERVAL)

    log.warning("CDP OTP injection timed out for %s", profile_email)
    return False
