# cdp_executor.py — CDP-based browser control (backup execution layer)
#
# Discovers ixBrowser's remote debugging port via psutil, attaches over CDP
# WebSocket, and provides element interaction without touching the OS mouse.
#
# Public API (synchronous):
#   ex = CDPExecutor()
#   ex.connect()              # auto-discover port (tries 9222 first)
#   ex.connect(port=9222)     # or supply port directly
#   ex.connect_ws("ws://...") # connect directly to known ws:// URL (IXBrowser API)
#   tree = ex.get_axtree()    # [{nodeId, role, name, properties, childIds}, ...]
#   ex.click_selector("#id")  # CDP click by CSS selector
#   ex.click_js(expr)         # evaluate JS expression that returns an element
#   ex.dispatch_click(x, y)   # CDP click at viewport coordinates
#   ex.type_text("hello")     # CDP keyboard injection
#   ex.scroll("down", 3)      # CDP mouse-wheel scroll
#   ex.navigate(url)          # navigate and wait for readyState=complete
#   ex.inject_stealth()       # inject stealth JS into future page loads
#   ex.screenshot_b64()       # CDP screenshot → base64 PNG string
#   ex.eval_js(expr)          # evaluate JS → JSON result
#   ex.disconnect()

from __future__ import annotations

import json
import math
import os
import random
import sys
import threading
import time
import urllib.request
from typing import Any, List, Optional, Tuple

# OS humanizer — real HID events via pyinterception / pynput
# Import from sibling package so clicks are indistinguishable from physical input.
_HAS_OS_HUMANIZER = False
try:
    _cb_core = os.path.normpath(os.path.join(os.path.dirname(__file__), ".."))
    if _cb_core not in sys.path:
        sys.path.insert(0, _cb_core)
    from humanizer_mcp._mouse import click as _hum_click  # type: ignore
    _HAS_OS_HUMANIZER = True
except Exception:
    pass

_CONNECT_TIMEOUT  = 3.0    # seconds for HTTP probe
_RECV_TIMEOUT     = 15.0   # seconds to wait for a CDP response
_IX_NAMES         = {"ixbrowser.exe", "ixbrowser", "chrome.exe", "chromium.exe",
                     "google chrome.exe"}

# Baseline stealth bundle — injected via addScriptToEvaluateOnNewDocument on every connect.
# Only patches that ixBrowser cannot handle natively at the C++ level.
# DO NOT add: timezone override, languages defineProperty, outerWidth/Height overrides,
# or userAgentData overrides — those cause Pixelscan masking detection.
_STEALTH_JS = r"""
(function() {
    // Remove automation globals
    Object.keys(window).filter(function(k) {
        return k.startsWith('cdc_') || k.includes('__puppeteer') || k.includes('__selenium')
            || k.includes('__webdriver') || k.includes('__driver');
    }).forEach(function(k) { try { delete window[k]; } catch(e) {} });

    // window.chrome must exist with loadTimes, csi, app, runtime
    if (!window.chrome) window.chrome = {};
    if (!window.chrome.runtime) window.chrome.runtime = {
        id: undefined,
        connect: function() {},
        sendMessage: function() {},
        onMessage: { addListener: function() {}, removeListener: function() {} },
        onConnect: { addListener: function() {}, removeListener: function() {} },
    };

    // Notification.permission should be 'default', not 'denied'
    // Headless/automation Chrome auto-denies; detectors (Sannysoft, Pixelscan) check this.
    try {
        if (typeof Notification !== 'undefined' && Notification.permission !== 'default') {
            Object.defineProperty(Notification, 'permission', {
                get: function() { return 'default'; },
                configurable: true,
            });
        }
    } catch(e) {}

    // Permissions.query — return 'prompt' for notifications/push
    // State values must be "granted" | "denied" | "prompt" (NOT "default")
    try {
        var _origQuery = window.Permissions && window.Permissions.prototype.query;
        if (_origQuery) {
            var _overrides = {notifications:'prompt', push:'prompt', geolocation:'prompt'};
            window.Permissions.prototype.query = function(d) {
                var state = _overrides[(d||{}).name];
                if (state) return Promise.resolve(
                    {state: state, onchange: null,
                     addEventListener: function(){}, removeEventListener: function(){}}
                );
                return _origQuery.call(this, d);
            };
        }
    } catch(e) {}
})();
"""


# ── Exceptions ────────────────────────────────────────────────────────────────

class CDPError(Exception):
    pass


# ── Helpers ───────────────────────────────────────────────────────────────────

def _http_get(url: str) -> Any:
    req = urllib.request.Request(url, headers={"User-Agent": "CareerBridge-CDP/1.0"})
    with urllib.request.urlopen(req, timeout=_CONNECT_TIMEOUT) as r:
        return json.loads(r.read())


def discover_cdp_port() -> int:
    """
    Return the ixBrowser CDP port. Tries 9222 first (fast path), then falls
    back to scanning process TCP connections for any listening Chrome/ixBrowser port.
    """
    # Fast path — ixBrowser always uses 9222 when launched via direct_launch_cdp.py
    try:
        data = _http_get("http://127.0.0.1:9222/json/version")
        if "webSocketDebuggerUrl" in data:
            return 9222
    except Exception:
        pass

    try:
        import psutil
    except ImportError:
        raise CDPError("psutil not installed — run: pip install psutil")

    candidate_ports: list[int] = []

    for proc in psutil.process_iter(["pid", "name"]):
        try:
            name = (proc.info.get("name") or "").lower()
            if not any(n in name for n in ("ixbrowser", "chrome", "chromium")):
                continue
            for conn in proc.connections(kind="tcp"):
                if conn.status == "LISTEN" and 1024 < conn.laddr.port < 65535:
                    candidate_ports.append(conn.laddr.port)
        except Exception:
            pass

    for port in dict.fromkeys(candidate_ports):  # dedupe, preserve order
        try:
            data = _http_get(f"http://127.0.0.1:{port}/json/version")
            if "webSocketDebuggerUrl" in data:
                return port
        except Exception:
            pass

    raise CDPError(
        "ixBrowser CDP port not found. "
        "Open ixBrowser, go to Settings → Advanced → Enable remote debugging."
    )


# ── CDPExecutor ───────────────────────────────────────────────────────────────

class CDPExecutor:
    """
    Synchronous CDP executor. Maintains one persistent WebSocket connection
    to the active ixBrowser page and dispatches CDP commands over it.
    """

    def __init__(self) -> None:
        self._port:   Optional[int]  = None
        self._ws                     = None   # websocket.WebSocketApp
        self._msg_id: int            = 0
        self._pending: dict          = {}     # id → (Event, list[response])
        self._lock    = threading.Lock()
        self._connected: bool        = False
        self._ws_ready  = threading.Event()  # set when WS handshake completes
        # Track simulated cursor position for realistic path generation
        self._cursor_x: float        = 400.0
        self._cursor_y: float        = 300.0

    # ── Connection ─────────────────────────────────────────────────────────────

    def _on_open(self, ws) -> None:
        self._ws_ready.set()

    def connect(self, port: Optional[int] = None) -> int:
        """Auto-discover ixBrowser port (or use supplied port) and attach."""
        try:
            import websocket  # websocket-client
        except ImportError:
            raise CDPError("websocket-client not installed — run: pip install websocket-client")

        self._port = port or discover_cdp_port()

        # Pick the most recently focused page
        targets = _http_get(f"http://127.0.0.1:{self._port}/json")
        pages   = [t for t in targets if t.get("type") == "page"]
        if not pages:
            raise CDPError(f"No open pages in browser on port {self._port}")

        ws_url = pages[0]["webSocketDebuggerUrl"]

        self._ws_ready.clear()
        self._ws = websocket.WebSocketApp(
            ws_url,
            on_open=self._on_open,
            on_message=self._on_message,
            on_error=self._on_error,
            on_close=self._on_close,
        )
        # suppress_origin: Chrome 111+ rejects connections whose Origin header
        # includes a port number. Suppressing it bypasses the check entirely.
        thread = threading.Thread(
            target=lambda: self._ws.run_forever(suppress_origin=True), daemon=True
        )
        thread.start()

        # Wait for confirmed handshake (up to 8 seconds)
        if not self._ws_ready.wait(timeout=8.0):
            raise CDPError(f"WebSocket handshake timed out for {ws_url}")
        time.sleep(0.1)  # small buffer after open

        # Enable the domains we'll use
        self._send("DOM.enable")
        self._send("Accessibility.enable")
        self._send("Page.enable")
        self._send("Page.addScriptToEvaluateOnNewDocument", {"source": _STEALTH_JS})
        self._connected = True

        return self._port

    def connect_ws(self, ws_url: str) -> None:
        """
        Connect to a known ws:// URL from the IXBrowser API.

        IXBrowser returns a browser-level URL (ws://.../devtools/browser/UUID).
        We detect this and fall back to port-based page discovery (/json) so we
        always land on a page session rather than the browser root.
        """
        import re
        try:
            import websocket
        except ImportError:
            raise CDPError("websocket-client not installed — run: pip install websocket-client")

        m = re.search(r":(\d+)/", ws_url)
        self._port = int(m.group(1)) if m else 0

        # Browser-level URL → use port-based page discovery instead
        if "/devtools/browser/" in ws_url and self._port:
            self.connect(port=self._port)
            return

        self._ws_ready.clear()
        self._ws = websocket.WebSocketApp(
            ws_url,
            on_open=self._on_open,
            on_message=self._on_message,
            on_error=self._on_error,
            on_close=self._on_close,
        )
        threading.Thread(
            target=lambda: self._ws.run_forever(suppress_origin=True), daemon=True
        ).start()

        if not self._ws_ready.wait(timeout=8.0):
            raise CDPError(f"WebSocket handshake timed out for {ws_url}")
        time.sleep(0.1)

        self._send("DOM.enable")
        self._send("Accessibility.enable")
        self._send("Page.enable")
        self._send("Page.addScriptToEvaluateOnNewDocument", {"source": _STEALTH_JS})
        self._connected = True

    def disconnect(self) -> None:
        if self._ws is not None:
            self._ws.close()
        self._connected = False

    def ping(self) -> bool:
        """Return True if the CDP connection is live."""
        try:
            self._send("Browser.getVersion")
            return True
        except Exception:
            return False

    # ── WebSocket callbacks ────────────────────────────────────────────────────

    def _on_message(self, ws, raw: str) -> None:
        try:
            data   = json.loads(raw)
            msg_id = data.get("id")
            if msg_id is None:
                return
            with self._lock:
                entry = self._pending.get(msg_id)
            if entry:
                ev, box = entry
                box.append(data)
                ev.set()
        except Exception:
            pass

    def _on_error(self, ws, exc) -> None:
        self._connected = False

    def _on_close(self, ws, *_) -> None:
        self._connected = False

    # ── Core send/receive ──────────────────────────────────────────────────────

    def _send(self, method: str, params: Optional[dict] = None) -> dict:
        with self._lock:
            self._msg_id += 1
            msg_id = self._msg_id
            ev  = threading.Event()
            box: list = []
            self._pending[msg_id] = (ev, box)

        self._ws.send(json.dumps({"id": msg_id, "method": method, "params": params or {}}))
        ev.wait(timeout=_RECV_TIMEOUT)

        with self._lock:
            self._pending.pop(msg_id, None)

        if not box:
            raise CDPError(f"CDP timeout waiting for '{method}'")
        resp = box[0]
        if "error" in resp:
            raise CDPError(f"CDP error from '{method}': {resp['error']}")
        return resp.get("result", {})

    # ── Accessibility tree ────────────────────────────────────────────────────

    def get_axtree(self) -> list[dict]:
        """
        Return the full accessibility tree as a flat list of node dicts.
        Each node: {nodeId, role, name, description, value, properties, childIds}
        Properties include: checked, selected, disabled, expanded, required, etc.
        """
        result = self._send("Accessibility.getFullAXTree")
        nodes  = result.get("nodes", [])
        out    = []
        for n in nodes:
            role = n.get("role", {}).get("value", "")
            if not role or role in ("none", "generic", "StaticText"):
                continue

            props = {}
            for p in n.get("properties", []):
                val = p.get("value", {})
                props[p["name"]] = val.get("value") if isinstance(val, dict) else val

            out.append({
                "nodeId":      n.get("nodeId"),
                "role":        role,
                "name":        n.get("name", {}).get("value", ""),
                "description": n.get("description", {}).get("value", ""),
                "value":       n.get("value", {}).get("value", ""),
                "properties":  props,
                "childIds":    n.get("childIds", []),
            })
        return out

    # ── Click ─────────────────────────────────────────────────────────────────

    def _get_screen_offset(self) -> Tuple[float, float]:
        """
        Return (offset_x, offset_y) to convert viewport coords to screen coords.
        offset_x = window.screenX (left edge of browser window on screen)
        offset_y = window.screenY + (outerHeight - innerHeight)  (top of content area)
        The chrome delta covers tab bar + address bar + bookmarks bar.
        """
        r = self.eval_js(
            "({sx: window.screenX, sy: window.screenY, "
            "ch: window.outerHeight - window.innerHeight})"
        ) or {}
        return float(r.get("sx", 0)), float(r.get("sy", 0)) + float(r.get("ch", 85))

    def _os_click(self, screen_x: float, screen_y: float) -> None:
        """
        Deliver a click via the OS humanizer (real HID path, no LLKHF_INJECTED).
        Falls back to CDP dispatch if the humanizer is unavailable.
        """
        if _HAS_OS_HUMANIZER:
            _hum_click(int(round(screen_x)), int(round(screen_y)))
        else:
            self._dispatch_click(screen_x, screen_y)

    def _resolve_element(self, selector: str) -> Tuple[float, float]:
        """Get viewport center (x, y) of element matching CSS selector."""
        script = f"""
        (function() {{
            var el = document.querySelector({json.dumps(selector)});
            if (!el) return null;
            var r = el.getBoundingClientRect();
            return {{x: r.left + r.width/2, y: r.top + r.height/2, found: true}};
        }})()
        """
        result = self.eval_js(script)
        if not result or not result.get("found"):
            raise CDPError(f"Selector not found: {selector!r}")
        return result["x"], result["y"]

    def click_selector(self, selector: str) -> None:
        """
        Click an element by CSS selector using OS-level HID events.
        CDP resolves the element coordinates; the OS humanizer delivers the click.
        """
        vx, vy = self._resolve_element(selector)
        ox, oy = self._get_screen_offset()
        self._os_click(ox + vx, oy + vy)

    def click_js(self, js_expr: str) -> None:
        """
        Click an element returned by a JS expression via OS-level HID events.
        E.g.: click_js('document.querySelector("button[aria-label=Submit]")')
        """
        script = f"""
        (function() {{
            var el = {js_expr};
            if (!el) return null;
            var r = el.getBoundingClientRect();
            return {{x: r.left + r.width/2, y: r.top + r.height/2, found: true}};
        }})()
        """
        result = self.eval_js(script)
        if not result or not result.get("found"):
            raise CDPError(f"JS expression returned no element: {js_expr!r}")
        vx, vy = result["x"], result["y"]
        ox, oy = self._get_screen_offset()
        self._os_click(ox + vx, oy + vy)

    # ── Human-like mouse path generation ─────────────────────────────────────

    @staticmethod
    def _bezier_path(
        x0: float, y0: float, x1: float, y1: float, n_steps: int = 30
    ) -> List[Tuple[float, float]]:
        """
        Cubic Bézier path with randomised one-sided control points.
        Mirrors ghost-cursor's approach: control points biased toward the
        direction of travel so the cursor curves naturally (not oscillates).
        """
        dist = math.hypot(x1 - x0, y1 - y0)
        jitter = max(15.0, dist * 0.20)

        # Control points: offset perpendicular to the travel vector
        dx, dy = x1 - x0, y1 - y0
        perp_x, perp_y = -dy, dx  # perpendicular direction
        perp_len = math.hypot(perp_x, perp_y) or 1.0
        perp_x /= perp_len
        perp_y /= perp_len

        deflect1 = random.uniform(0.1, 0.4) * jitter * random.choice([-1, 1])
        deflect2 = random.uniform(0.1, 0.3) * jitter * random.choice([-1, 1])

        cx1 = x0 + dx * 0.3 + perp_x * deflect1
        cy1 = y0 + dy * 0.3 + perp_y * deflect1
        cx2 = x0 + dx * 0.7 + perp_x * deflect2
        cy2 = y0 + dy * 0.7 + perp_y * deflect2

        def ease(t: float) -> float:
            return t * t * (3 - 2 * t)  # smooth-step (slow→fast→slow)

        path = []
        for i in range(n_steps + 1):
            t = ease(i / n_steps)
            u = 1 - t
            px = u**3*x0 + 3*u**2*t*cx1 + 3*u*t**2*cx2 + t**3*x1
            py = u**3*y0 + 3*u**2*t*cy1 + 3*u*t**2*cy2 + t**3*y1
            # Physiological tremor: ±1px Gaussian noise
            path.append((px + random.gauss(0, 0.6), py + random.gauss(0, 0.6)))
        return path

    def _move_mouse_to(self, x: float, y: float) -> None:
        """
        Dispatch mouseMoved CDP events along a Bézier path from current
        tracked position to (x, y).  Step delay targets ~180 Hz.
        """
        dist = math.hypot(x - self._cursor_x, y - self._cursor_y)
        if dist < 2:
            return

        # Fitts's Law: longer moves take more time
        duration = 0.20 + 0.12 * math.sqrt(dist / 500.0)
        path = self._bezier_path(self._cursor_x, self._cursor_y, x, y,
                                  n_steps=max(15, int(dist / 8)))
        step_delay = duration / len(path)
        ts = time.time()

        for px, py in path:
            self._send("Input.dispatchMouseEvent", {
                "type": "mouseMoved",
                "x": px, "y": py,
                "button": "none",
                "modifiers": 0,
                "timestamp": ts,
            })
            ts += step_delay
            deadline = time.perf_counter() + step_delay
            while time.perf_counter() < deadline:
                pass  # busy-wait for sub-ms accuracy

        self._cursor_x, self._cursor_y = x, y

    def _dispatch_click(self, x: float, y: float) -> None:
        """
        Full humanized CDP click:
          1. Move mouse along Bézier path to target
          2. 30% chance of overshoot + correction for long moves
          3. Pre-click hover dwell (ex-Gaussian)
          4. Tiny jitter on final position (humans don't hit exact center)
          5. mousePressed → hold → mouseReleased
        """
        dist = math.hypot(x - self._cursor_x, y - self._cursor_y)

        # Overshoot on long moves (>280px, 30% chance)
        if dist > 280 and random.random() < 0.30:
            angle = random.uniform(0, 2 * math.pi)
            over = random.randint(3, 9)
            ox, oy = x + over * math.cos(angle), y + over * math.sin(angle)
            self._move_mouse_to(ox, oy)
            time.sleep(random.uniform(0.04, 0.11))
            self._cursor_x, self._cursor_y = ox, oy

        self._move_mouse_to(x, y)

        # Pre-click hover: ex-Gaussian (mean ~120ms)
        hover = max(0.06, random.gauss(0.10, 0.03) + random.expovariate(14))
        time.sleep(hover)

        # Micro-jitter: click 0-2px from exact center (humans aren't perfect)
        jx = x + random.uniform(-2, 2)
        jy = y + random.uniform(-2, 2)
        ts = time.time()

        base = {"x": jx, "y": jy, "button": "left", "clickCount": 1,
                "modifiers": 0, "timestamp": ts}
        self._send("Input.dispatchMouseEvent", {**base, "type": "mousePressed"})
        # Ex-Gaussian hold: mean ~95ms, tail up to ~200ms
        hold = max(0.04, random.gauss(0.08, 0.022) + random.expovariate(15))
        time.sleep(hold)
        self._send("Input.dispatchMouseEvent", {**base, "type": "mouseReleased",
                                                 "timestamp": ts + hold})
        # Post-click micro-drift (humans don't freeze after clicking)
        time.sleep(random.uniform(0.03, 0.07))

    def dispatch_click(self, x: float, y: float) -> None:
        """Click at viewport coordinates (x, y) — public alias for coordinate-based clicks."""
        self._dispatch_click(x, y)

    # ── Typing ────────────────────────────────────────────────────────────────

    # Key code → (windowsVirtualKeyCode, code string) for special keys
    _SPECIAL_KEYS: dict = {
        "\n":  (13,  "Enter",     "Enter"),
        "\r":  (13,  "Enter",     "Enter"),
        "\t":  (9,   "Tab",       "Tab"),
        "\b":  (8,   "Backspace", "Backspace"),
        " ":   (32,  "Space",     " "),
    }

    def type_text(self, text: str) -> None:
        """
        Type text via CDP Input.dispatchKeyEvent (keyDown + char + keyUp).
        Fires keydown/keypress/keyup browser events — unlike insertText which
        bypasses them and is trivially detectable.

        Timing: ex-Gaussian IKI + bigram acceleration + fatigue.
        Error simulation: 3% QWERTY-adjacent typo followed by Backspace.
        """
        prev = ""
        chars_typed = 0
        _qwerty_adj: dict = {
            'a': 'qwsz', 'b': 'vghn', 'c': 'xdfv', 'd': 'sexcrf',
            'e': 'wrsdf', 'f': 'drtgvc', 'g': 'ftyhjb', 'h': 'gyujnb',
            'i': 'uojk', 'j': 'hukimn', 'k': 'jilom', 'l': 'kop',
            'm': 'njk', 'n': 'bhjm', 'o': 'iplk', 'p': 'ol',
            'q': 'wa', 'r': 'etdf', 's': 'qwedxza', 't': 'ryfg',
            'u': 'yihj', 'v': 'cfgb', 'w': 'qeasz', 'x': 'zsdc',
            'y': 'tugh', 'z': 'asx',
        }

        for i, ch in enumerate(text):
            # QWERTY typo at ~3% rate (alphabetic chars only)
            if ch.isalpha() and random.random() < 0.03:
                adj = _qwerty_adj.get(ch.lower(), "")
                if adj:
                    wrong = random.choice(adj)
                    self._dispatch_key_event(wrong)
                    time.sleep(max(0.08, random.gauss(0.16, 0.05)))
                    self._dispatch_key_event("\b")  # backspace
                    time.sleep(max(0.04, random.gauss(0.07, 0.02)))

            self._dispatch_key_event(ch)
            chars_typed += 1

            if i < len(text) - 1:
                # Ex-Gaussian IKI
                iki = max(0.035, random.gauss(0.065, 0.022) + random.expovariate(13))

                # Bigram acceleration for common English pairs
                bigram = (prev + ch).lower()
                fast = {'th', 'he', 'in', 'er', 'an', 're', 'on', 'at', 'st',
                        'nd', 'to', 'io', 'or', 'is', 'it', 'ng', 've', 'me'}
                if bigram in fast:
                    iki *= 0.62
                elif prev and ch and prev.lower() in 'aeiou' and ch.lower() not in 'aeiou':
                    iki *= 0.90  # vowel→consonant is slightly faster

                # Fatigue: 0.04% slowdown per char
                iki *= 1.0 + chars_typed * 0.0004

                # Longer pause after spaces and punctuation
                if ch == " ":
                    iki *= random.uniform(1.15, 1.40)
                elif ch in ".,;:!?":
                    iki *= random.uniform(1.25, 1.70)

                time.sleep(iki)

            prev = ch

    def _dispatch_key_event(self, ch: str) -> None:
        """Dispatch keyDown + char + keyUp for one character or special key."""
        ts = time.time()
        hold = max(0.018, random.gauss(0.045, 0.012))

        if ch in self._SPECIAL_KEYS:
            vk, code, key = self._SPECIAL_KEYS[ch]
            self._send("Input.dispatchKeyEvent", {
                "type": "keyDown", "key": key, "code": code,
                "windowsVirtualKeyCode": vk, "nativeVirtualKeyCode": vk,
                "modifiers": 0, "timestamp": ts,
            })
            time.sleep(hold)
            self._send("Input.dispatchKeyEvent", {
                "type": "keyUp", "key": key, "code": code,
                "windowsVirtualKeyCode": vk, "nativeVirtualKeyCode": vk,
                "modifiers": 0, "timestamp": ts + hold,
            })
        else:
            vk = ord(ch.upper()) if ch.isalpha() else ord(ch)
            self._send("Input.dispatchKeyEvent", {
                "type": "keyDown", "key": ch, "code": f"Key{ch.upper()}" if ch.isalpha() else "Unidentified",
                "windowsVirtualKeyCode": vk, "modifiers": 0, "timestamp": ts,
            })
            time.sleep(hold * 0.4)
            self._send("Input.dispatchKeyEvent", {
                "type": "char", "key": ch, "text": ch,
                "modifiers": 0, "timestamp": ts + hold * 0.4,
            })
            time.sleep(hold * 0.6)
            self._send("Input.dispatchKeyEvent", {
                "type": "keyUp", "key": ch, "code": f"Key{ch.upper()}" if ch.isalpha() else "Unidentified",
                "windowsVirtualKeyCode": vk, "modifiers": 0, "timestamp": ts + hold,
            })

    # ── Scroll ────────────────────────────────────────────────────────────────

    def scroll(self, direction: str = "down", clicks: int = 3) -> None:
        """
        Scroll via CDP Input.dispatchMouseEvent mouseWheel events.
        Fires native wheel listeners (unlike window.scrollBy which bypasses them).
        Uses multi-burst pattern with Weibull-distributed pauses.
        """
        dy_per_notch = 100  # px per notch (Chrome default wheel delta)
        dy_sign = -1 if direction == "down" else 1
        remaining = clicks

        while remaining > 0:
            burst = min(remaining, random.choices([1, 2, 3], weights=[3, 5, 2])[0])
            remaining -= burst
            ts = time.time()

            self._send("Input.dispatchMouseEvent", {
                "type": "mouseWheel",
                "x": self._cursor_x,
                "y": self._cursor_y,
                "deltaX": 0,
                "deltaY": dy_sign * burst * dy_per_notch,
                "modifiers": 0,
                "timestamp": ts,
            })

            if remaining > 0:
                # Weibull inter-burst pause (shape 1.5, scale 0.13 → ~100ms modal)
                k, lam = 1.5, 0.13
                u = random.random()
                if u >= 1.0:
                    u = 0.9999
                pause = max(0.05, lam * (-math.log(1 - u)) ** (1 / k))
                time.sleep(pause)

    def navigate(self, url: str, timeout: float = 25.0) -> None:
        """
        Navigate to url and wait for readyState=complete. Falls back to JS
        location assignment if Page.navigate times out (in-flight nav conflict).
        """
        try:
            self._send("Page.enable")
            self._send("Page.navigate", {"url": url})
        except CDPError:
            try:
                self._send("Runtime.evaluate", {
                    "expression":    f"window.location.href = {json.dumps(url)}",
                    "returnByValue": False,
                    "awaitPromise":  False,
                })
            except CDPError:
                pass
        self.wait_for_load(timeout=timeout)

    # ── Load waiting ──────────────────────────────────────────────────────────

    def wait_for_load(self, timeout: float = 25.0) -> None:
        """Poll until document.readyState === 'complete' or timeout."""
        deadline = time.time() + timeout
        while time.time() < deadline:
            try:
                if self.eval_js("document.readyState") == "complete":
                    return
            except Exception:
                pass
            time.sleep(0.3)

    # ── Stealth ───────────────────────────────────────────────────────────────

    def inject_stealth(self) -> None:
        """
        Register the stealth JS bundle to run on every new document load.
        Already called automatically by connect() — call this again only if
        you reconnect to a different page or need to re-register after a crash.
        """
        self._send("Page.addScriptToEvaluateOnNewDocument", {"source": _STEALTH_JS})

    # ── Screenshot ────────────────────────────────────────────────────────────

    def screenshot_b64(self) -> str:
        """
        Capture the current page via CDP and return a base64-encoded PNG.
        Works regardless of window focus or visibility — no Win32 required.
        Retries up to 3 times on empty response.
        """
        for _ in range(3):
            result = self._send("Page.captureScreenshot", {
                "format": "png",
                "captureBeyondViewport": False,
            })
            data = result.get("data")
            if data:
                return data
            time.sleep(1.0)
        raise CDPError("CDP screenshot returned empty data after 3 attempts")


    # ── JS evaluation ─────────────────────────────────────────────────────────

    def eval_js(self, expression: str) -> Any:
        """Evaluate a JS expression and return the JSON-serialisable result."""
        result = self._send("Runtime.evaluate", {
            "expression":            expression,
            "returnByValue":         True,
            "awaitPromise":          False,
            "userGesture":           True,
        })
        obj = result.get("result", {})
        if obj.get("type") == "object" and obj.get("value") is not None:
            return obj["value"]
        return obj.get("value")

    def eval_js_async(self, expression: str) -> Any:
        """Evaluate a JS expression that returns a Promise, awaiting its resolution.

        Uses the same _RECV_TIMEOUT as other CDP calls. The Promise itself should
        resolve within that window — include a JS-side setTimeout guard if needed.
        """
        result = self._send("Runtime.evaluate", {
            "expression":            expression,
            "returnByValue":         True,
            "awaitPromise":          True,
            "userGesture":           True,
        })
        obj = result.get("result", {})
        if obj.get("type") == "object" and obj.get("value") is not None:
            return obj["value"]
        return obj.get("value")

    # ── Page info ─────────────────────────────────────────────────────────────

    def get_page_info(self) -> dict:
        """Return {url, title} for the active page."""
        result = self.eval_js("({url: location.href, title: document.title})")
        return result or {}
