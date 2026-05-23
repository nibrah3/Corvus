# cdp_executor.py — CDP-based browser control (backup execution layer)
#
# Discovers ixBrowser's remote debugging port via psutil, attaches over CDP
# WebSocket, and provides element interaction without touching the OS mouse.
#
# Public API (synchronous):
#   ex = CDPExecutor()
#   ex.connect()              # auto-discover port (tries 9222 first)
#   ex.connect(port=9222)     # or supply port directly
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
import threading
import time
import urllib.request
from typing import Any, Optional

_CONNECT_TIMEOUT  = 3.0    # seconds for HTTP probe
_RECV_TIMEOUT     = 15.0   # seconds to wait for a CDP response
_IX_NAMES         = {"ixbrowser.exe", "ixbrowser", "chrome.exe", "chromium.exe",
                     "google chrome.exe"}

# Minimal stealth bundle — confirmed CONSISTENT on Pixelscan with no masking detection.
# Only patches that ixBrowser cannot handle natively at the C++ level.
# DO NOT add: timezone override, languages defineProperty, permissions.query replacement,
# outerWidth/Height, or userAgentData overrides — all cause Pixelscan masking detection.
_STEALTH_JS = r"""
(function() {
    Object.keys(window).filter(function(k) {
        return k.startsWith('cdc_') || k.includes('__puppeteer') || k.includes('__selenium');
    }).forEach(function(k) { try { delete window[k]; } catch(e) {} });
    if (!window.chrome) window.chrome = {};
    if (!window.chrome.runtime) window.chrome.runtime = {
        id: undefined,
        connect: function() {},
        sendMessage: function() {},
        onMessage: { addListener: function() {}, removeListener: function() {} }
    };
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

    # ── Connection ─────────────────────────────────────────────────────────────

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

        self._ws = websocket.WebSocketApp(
            ws_url,
            on_message=self._on_message,
            on_error=self._on_error,
            on_close=self._on_close,
        )
        thread = threading.Thread(target=self._ws.run_forever, daemon=True)
        thread.start()
        time.sleep(0.8)   # let the WS handshake complete

        # Enable the domains we'll use
        self._send("DOM.enable")
        self._send("Accessibility.enable")
        self._send("Page.enable")
        self._send("Page.addScriptToEvaluateOnNewDocument", {"source": _STEALTH_JS})
        self._connected = True

        return self._port

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

    def click_selector(self, selector: str) -> None:
        """
        Click an element by CSS selector.
        Uses getBoundingClientRect → dispatches mouse events at element centre.
        """
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
        x, y = result["x"], result["y"]
        self._dispatch_click(x, y)

    def click_js(self, js_expr: str) -> None:
        """
        Click an element returned by a JS expression (must return an Element).
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
        self._dispatch_click(result["x"], result["y"])

    def _dispatch_click(self, x: float, y: float) -> None:
        """Send mousePressed + mouseReleased at (x, y) via CDP Input events."""
        base = {"x": x, "y": y, "button": "left", "clickCount": 1, "modifiers": 0}
        self._send("Input.dispatchMouseEvent", {**base, "type": "mousePressed"})
        self._send("Input.dispatchMouseEvent", {**base, "type": "mouseReleased"})

    def dispatch_click(self, x: float, y: float) -> None:
        """Click at viewport coordinates (x, y) — public alias for coordinate-based clicks."""
        self._dispatch_click(x, y)

    # ── Typing ────────────────────────────────────────────────────────────────

    def type_text(self, text: str) -> None:
        """
        Inject text character-by-character via CDP Input.insertText events.
        Applies Gaussian inter-key delay for natural timing.
        """
        for ch in text:
            self._send("Input.insertText", {"text": ch})

    # ── Scroll ────────────────────────────────────────────────────────────────

    def scroll(self, direction: str = "down", clicks: int = 3) -> None:
        """Scroll the page using window.scrollBy (works on all page types)."""
        delta = clicks * 300 if direction == "down" else -clicks * 300
        for _ in range(abs(clicks)):
            self.eval_js(f"window.scrollBy(0, {delta // abs(clicks)})")

    def navigate(self, url: str, timeout: float = 25.0) -> None:
        """Navigate to a URL and wait for document.readyState === 'complete'."""
        self._send("Page.navigate", {"url": url})
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

    # ── Page info ─────────────────────────────────────────────────────────────

    def get_page_info(self) -> dict:
        """Return {url, title} for the active page."""
        result = self.eval_js("({url: location.href, title: document.title})")
        return result or {}
