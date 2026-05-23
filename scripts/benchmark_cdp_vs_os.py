"""
benchmark_cdp_vs_os.py — Head-to-head latency benchmark: CDP-only vs CDP+OS.

Test flow (3 real pages, no auth required):
  1. https://the-internet.herokuapp.com/login  — fill and submit form
  2. /secure                                   — scroll, read page
  3. click Logout                              → back to /login
  Repeat cycle once more so we get stable average timings.

Metrics captured per operation:
  navigate_ms     — page.navigate + load wait
  resolve_ms      — CDP getBoundingClientRect call
  offset_ms       — JS window.screenX/Y query (OS mode only)
  click_ms        — click delivery (CDP dispatch OR OS HID)
  type_ms         — type_text for N characters
  scroll_ms       — scroll dispatch
  total_ms        — wall-clock for full cycle

Run requirements:
  - pip install websocket-client pynput psutil
  - Chrome: launched automatically by this script
  - IXBrowser: NOT needed (uses plain Chrome)

Usage:
  python scripts/benchmark_cdp_vs_os.py
  python scripts/benchmark_cdp_vs_os.py --cdp-port 9222 --cycles 2
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
import threading
from typing import Any, Dict, List, Optional, Tuple

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from careerbridge.cdp_executor import CDPExecutor, CDPError, _HAS_OS_HUMANIZER, _hum_click  # type: ignore

# ── Constants ─────────────────────────────────────────────────────────────────

CHROME_PATHS = [
    r"C:\Program Files\Google\Chrome\Application\chrome.exe",
    r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
]
CDP_PORT   = 9223   # use 9223 to avoid clashing with IXBrowser on 9222
HTTP_PORT  = 18080  # local test server

USERNAME   = "testuser"
PASSWORD   = "hunter2abc"

# ── Local test server (3 pages, multi-step form) ───────────────────────────────

_PAD = "x " * 600   # ~1200px of text to enable scrolling

# Single-page test: all element types, long enough to scroll
_TEST_PAGE = (
    "data:text/html,<!DOCTYPE html><html><head><title>CDP Bench</title></head>"
    "<body style='font-family:sans-serif;padding:20px'>"
    "<h2>Section 1 - Login</h2>"
    "<input id='username' type='text' placeholder='Username' style='display:block;margin:8px 0'><br>"
    "<input id='password' type='password' placeholder='Password' style='display:block;margin:8px 0'><br>"
    "<button id='login' style='margin:8px 0'>Login</button>"
    "<p style='margin:40px 0'>" + _PAD + "</p>"
    "<h2>Section 2 - Preferences</h2>"
    "<textarea id='bio' rows='4' cols='50' placeholder='About you' style='display:block;margin:8px 0'></textarea><br>"
    "<label style='margin:8px'><input type='radio' name='sz' id='r1' value='sm'> Small</label>"
    "<label style='margin:8px'><input type='radio' name='sz' id='r2' value='lg'> Large</label><br><br>"
    "<button id='save' style='margin:8px 0'>Save</button>"
    "<p style='margin:40px 0'>" + _PAD + "</p>"
    "<h2>Section 3 - Extra fields</h2>"
    "<input id='email' type='email' placeholder='Email' style='display:block;margin:8px 0'><br>"
    "<input id='phone' type='tel' placeholder='Phone' style='display:block;margin:8px 0'><br>"
    "<button id='submit' style='margin:8px 0'>Submit</button>"
    "</body></html>"
)


def _start_local_server(port: int) -> threading.Thread:
    # Not used now but kept for future expansion
    return threading.Thread(target=lambda: None, daemon=True)

# ── Instrumented executor ─────────────────────────────────────────────────────

class BenchmarkCDPExecutor(CDPExecutor):
    """
    Wraps CDPExecutor to measure each operation independently.
    cdp_only=True: forces all clicks through CDP Input.dispatchMouseEvent
    cdp_only=False: routes clicks through OS humanizer (pynput/interception)
    """

    def __init__(self, cdp_only: bool = False) -> None:
        super().__init__()
        self.cdp_only   = cdp_only
        self.log: List[Dict[str, Any]] = []

    def _t(self, label: str, fn):
        t0 = time.perf_counter()
        result = fn()
        ms = (time.perf_counter() - t0) * 1000
        self.log.append({"op": label, "ms": round(ms, 2)})
        return result

    # ── Override click_selector to instrument and mode-switch ─────────────────

    def click_selector(self, selector: str) -> None:
        vx, vy = self._t("resolve", lambda: self._resolve_element(selector))

        if self.cdp_only:
            # Purely CDP: Bézier path + mousePressed/Released
            self._t("click_cdp", lambda: self._dispatch_click(vx, vy))
        else:
            # CDP resolves coords; OS delivers the click
            ox, oy = self._t("offset", lambda: self._get_screen_offset())
            sx, sy = ox + vx, oy + vy
            if _HAS_OS_HUMANIZER:
                self._t("click_os", lambda: _hum_click(int(round(sx)), int(round(sy))))
            else:
                # Fallback: still CDP but note it
                self._t("click_os_fallback", lambda: self._dispatch_click(vx, vy))

    def type_text(self, text: str) -> None:
        self._t(f"type_{len(text)}ch", lambda: CDPExecutor.type_text(self, text))

    def navigate(self, url: str, timeout: float = 12.0) -> None:
        self._t("navigate", lambda: CDPExecutor.navigate(self, url, timeout))

    def scroll(self, direction: str = "down", clicks: int = 3) -> None:
        self._t("scroll", lambda: CDPExecutor.scroll(self, direction, clicks))


# ── Chrome launcher ───────────────────────────────────────────────────────────

def launch_chrome(port: int) -> Optional[subprocess.Popen]:
    chrome = next((p for p in CHROME_PATHS if os.path.exists(p)), None)
    if not chrome:
        return None
    import shutil, urllib.request as _ur
    # Clean profile dir so Chrome never shows restore/welcome dialogs
    prof = r"C:\tmp\chrome_bench_profile"
    if os.path.exists(prof):
        shutil.rmtree(prof, ignore_errors=True)

    proc = subprocess.Popen([
        chrome,
        f"--remote-debugging-port={port}",
        "--remote-allow-origins=*",
        "--no-first-run",
        "--no-default-browser-check",
        "--disable-extensions",
        "--disable-sync",
        f"--user-data-dir={prof}",
        "--start-maximized",
    ], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

    # Poll until /json/list has at least one 'page' target
    deadline = time.time() + 15
    while time.time() < deadline:
        try:
            data = json.loads(_ur.urlopen(f"http://127.0.0.1:{port}/json/list", timeout=1).read())
            if any(t.get("type") == "page" for t in data):
                time.sleep(0.6)
                return proc
        except Exception:
            pass
        time.sleep(0.4)

    proc.terminate()
    raise RuntimeError(f"Chrome CDP port {port}: no page target found within 15 seconds")



# ── Test flow ─────────────────────────────────────────────────────────────────

def run_login_cycle(ex: BenchmarkCDPExecutor, cycle: int, http_port: int) -> None:
    """
    Multi-section test on a single stable data: page.
    Simulates a 3-section application form — login inputs, preferences,
    extra fields — with scrolling between sections.
    No page navigation = no runtime-reset race conditions.
    """
    print(f"    cycle {cycle+1} — load page…")
    ex.navigate(_TEST_PAGE)
    time.sleep(0.5)

    # ── Section 1: Login inputs ────────────────────────────────────────────────
    print(f"    cycle {cycle+1} — S1: click + type (username + password + button)…")
    ex.click_selector("#username")
    time.sleep(0.12)
    ex.type_text(USERNAME)
    time.sleep(0.12)

    ex.click_selector("#password")
    time.sleep(0.12)
    ex.type_text(PASSWORD)
    time.sleep(0.12)

    ex.click_selector("#login")
    time.sleep(0.15)

    # ── Scroll down to Section 2 ───────────────────────────────────────────────
    print(f"    cycle {cycle+1} — scroll to S2…")
    ex.scroll("down", 5)
    time.sleep(0.2)
    ex.scroll("down", 5)
    time.sleep(0.15)

    # ── Section 2: Preferences ────────────────────────────────────────────────
    print(f"    cycle {cycle+1} — S2: textarea + radio + save…")
    ex.click_selector("#bio")
    time.sleep(0.12)
    ex.type_text("Experienced professional seeking remote opportunities.")
    time.sleep(0.12)

    ex.click_selector("#r1")
    time.sleep(0.1)
    ex.click_selector("#r2")
    time.sleep(0.12)

    ex.click_selector("#save")
    time.sleep(0.15)

    # ── Scroll down to Section 3 ───────────────────────────────────────────────
    print(f"    cycle {cycle+1} — scroll to S3…")
    ex.scroll("down", 5)
    time.sleep(0.2)
    ex.scroll("down", 5)
    time.sleep(0.15)

    # ── Section 3: Extra fields ───────────────────────────────────────────────
    print(f"    cycle {cycle+1} — S3: email + phone + submit…")
    ex.click_selector("#email")
    time.sleep(0.12)
    ex.type_text("user@example.com")
    time.sleep(0.12)

    ex.click_selector("#phone")
    time.sleep(0.12)
    ex.type_text("+1 555 0100")
    time.sleep(0.12)

    ex.click_selector("#submit")
    time.sleep(0.15)

    # Scroll back up for the next cycle
    ex.scroll("up", 15)
    time.sleep(0.2)

    print(f"    cycle {cycle+1} done")


# ── Single mode runner ────────────────────────────────────────────────────────

def run_mode(port: int, cdp_only: bool, cycles: int, http_port: int = HTTP_PORT) -> List[Dict]:
    label = "CDP-ONLY" if cdp_only else "CDP+OS"
    print(f"\n{'='*60}")
    print(f"  MODE: {label}  |  cycles={cycles}")
    print(f"{'='*60}")

    ex = BenchmarkCDPExecutor(cdp_only=cdp_only)
    ex.connect(port=port)

    t_total = time.perf_counter()
    for i in range(cycles):
        run_login_cycle(ex, i, http_port)
    total_ms = (time.perf_counter() - t_total) * 1000

    ex.disconnect()

    # Aggregate
    by_op: Dict[str, List[float]] = {}
    for entry in ex.log:
        by_op.setdefault(entry["op"], []).append(entry["ms"])

    print(f"\n  Per-operation averages ({label}):")
    rows = []
    for op, vals in sorted(by_op.items()):
        avg  = sum(vals) / len(vals)
        mn   = min(vals)
        mx   = max(vals)
        cnt  = len(vals)
        print(f"    {op:<22} avg={avg:7.1f}ms  min={mn:6.1f}  max={mx:6.1f}  n={cnt}")
        rows.append({"op": op, "avg_ms": round(avg, 1), "min_ms": round(mn, 1),
                     "max_ms": round(mx, 1), "count": cnt})

    print(f"\n  Total wall-clock: {total_ms:.0f}ms ({total_ms/1000:.1f}s)")
    rows.append({"op": "_total", "avg_ms": round(total_ms, 1),
                 "min_ms": round(total_ms, 1), "max_ms": round(total_ms, 1), "count": 1})

    return rows


# ── Comparison table ──────────────────────────────────────────────────────────

def print_comparison(cdp_rows: List[Dict], os_rows: List[Dict]) -> None:
    print(f"\n{'='*70}")
    print("  COMPARISON TABLE")
    print(f"{'='*70}")
    hdr = f"  {'Operation':<22}  {'CDP-only':>10}  {'CDP+OS':>10}  {'Δ (OS-CDP)':>12}  {'Winner':>8}"
    print(hdr)
    print("  " + "-" * 66)

    cdp_map = {r["op"]: r["avg_ms"] for r in cdp_rows}
    os_map  = {r["op"]: r["avg_ms"] for r in os_rows}
    all_ops = sorted(set(cdp_map) | set(os_map))

    for op in all_ops:
        c = cdp_map.get(op)
        o = os_map.get(op)
        if c is None or o is None:
            print(f"  {op:<22}  {'N/A':>10}  {'N/A':>10}  {'N/A':>12}  {'—':>8}")
            continue
        delta = o - c
        winner = "CDP" if delta > 0 else "OS" if delta < 0 else "TIE"
        sign   = "+" if delta >= 0 else ""
        print(f"  {op:<22}  {c:>9.1f}ms  {o:>9.1f}ms  {sign}{delta:>9.1f}ms  {winner:>8}")

    print(f"\n  Notes:")
    print(f"    CDP-only click = Bézier path via CDP mouseMoved events + mousePressed/Released")
    print(f"    CDP+OS click   = CDP resolves element rect → OS humanizer (pynput) delivers HID")
    if not _HAS_OS_HUMANIZER:
        print(f"    ⚠  pyinterception not installed — OS mode fell back to CDP dispatch")
    print(f"    offset_ms      = extra JS call (window.screenX/Y) in OS mode only")
    print(f"    Stealth edge   = OS events carry no LLKHF_INJECTED flag (CDP events do)")


# ── Main ──────────────────────────────────────────────────────────────────────

def main() -> None:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--cdp-port",  type=int, default=CDP_PORT)
    p.add_argument("--cycles",    type=int, default=2, help="Login cycles per mode")
    p.add_argument("--no-launch", action="store_true",
                   help="Skip Chrome auto-launch (assume already running)")
    args = p.parse_args()

    proc = None
    if not args.no_launch:
        print(f"Launching Chrome on port {args.cdp_port}…")
        proc = launch_chrome(args.cdp_port)
        if not proc:
            print("ERROR: Chrome not found. Set --no-launch if Chrome is already running.")
            sys.exit(1)
        print(f"Chrome PID={proc.pid}")
    else:
        print(f"Using existing Chrome on port {args.cdp_port}")

    try:
        print(f"Starting local test HTTP server on port {HTTP_PORT}…")
        _start_local_server(HTTP_PORT)
        time.sleep(0.3)

        cdp_rows = run_mode(args.cdp_port, cdp_only=True,  cycles=args.cycles, http_port=HTTP_PORT)
        time.sleep(1.5)
        os_rows  = run_mode(args.cdp_port, cdp_only=False, cycles=args.cycles, http_port=HTTP_PORT)
        print_comparison(cdp_rows, os_rows)
    finally:
        if proc:
            proc.terminate()
            print("\nChrome terminated.")


if __name__ == "__main__":
    main()
