# scripts/test_cdp.py
#
# Full CDP test suite against a live ixBrowser session.
#
# Run order:
#   1. Open ixBrowser and launch a profile (after running ixbrowser_cdp_inject.py)
#   2. Navigate to a test page in that profile
#   3. Run: python scripts/test_cdp.py
#
# Each test prints PASS / FAIL / SKIP with a reason.
# A final summary shows what works, what needs fixing.

import sys
import os
import json
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from careerbridge.cdp_executor import CDPExecutor, CDPError, discover_cdp_port

SEP = "-" * 60
results: list[tuple[str, str, str]] = []  # (name, status, detail)


def record(name: str, status: str, detail: str = ""):
    results.append((name, status, detail))
    mark = {"PASS": "✓", "FAIL": "✗", "SKIP": "~"}.get(status, "?")
    print(f"  {mark} {name}: {detail}")


# ── Test helpers ──────────────────────────────────────────────────────────────

def test_port_discovery():
    print(SEP)
    print("TEST 1 — Port Discovery (psutil scan)")
    try:
        port = discover_cdp_port()
        if port:
            record("port_discovery", "PASS", f"found port {port}")
            return port
        else:
            record("port_discovery", "FAIL", "no ixBrowser CDP port found — run ixbrowser_cdp_inject.py first")
            return None
    except Exception as e:
        record("port_discovery", "FAIL", str(e))
        return None


def test_connect(ex: CDPExecutor):
    print(SEP)
    print("TEST 2 — WebSocket Connect + Domain Enable")
    try:
        port = ex.connect()
        record("connect", "PASS", f"connected on port {port}")
        return True
    except CDPError as e:
        record("connect", "FAIL", str(e))
        return False


def test_page_info(ex: CDPExecutor):
    print(SEP)
    print("TEST 3 — Page Info (URL + Title)")
    try:
        info = ex.get_page_info()
        record("page_info", "PASS", f"url={info.get('url','?')[:60]}  title={info.get('title','?')[:40]}")
    except Exception as e:
        record("page_info", "FAIL", str(e))


def test_eval_js(ex: CDPExecutor):
    print(SEP)
    print("TEST 4 — JS Evaluation")
    try:
        result = ex.eval_js("1 + 1")
        if result == 2:
            record("eval_js", "PASS", "1+1=2")
        else:
            record("eval_js", "FAIL", f"unexpected result: {result!r}")
    except Exception as e:
        record("eval_js", "FAIL", str(e))


def test_axtree(ex: CDPExecutor):
    print(SEP)
    print("TEST 5 — Accessibility Tree")
    try:
        tree = ex.get_axtree()
        roles = [n.get("role") for n in tree[:5]]
        record("axtree", "PASS", f"{len(tree)} nodes, top roles: {roles}")
    except Exception as e:
        record("axtree", "FAIL", str(e))


def test_dom_interactives(ex: CDPExecutor):
    print(SEP)
    print("TEST 6 — DOM extractInteractives() via cbWalker")
    try:
        raw = ex.eval_js("typeof window.cbWalker !== 'undefined' ? 'yes' : 'no'")
        if raw != "yes":
            record("dom_interactives", "SKIP", "cbWalker not loaded — open dom_mcp extension in ixBrowser")
            return
        result = ex.eval_js("JSON.stringify(window.cbWalker.extractInteractives())")
        elements = json.loads(result)
        record("dom_interactives", "PASS", f"{len(elements)} interactive elements found")
        for el in elements[:3]:
            print(f"      id={el.get('id')} role={el.get('role')} name={el.get('name','')[:40]}")
    except Exception as e:
        record("dom_interactives", "FAIL", str(e))


def test_scroll(ex: CDPExecutor):
    print(SEP)
    print("TEST 7 — Scroll")
    try:
        ex.scroll("down", 3)
        time.sleep(0.3)
        ex.scroll("up", 3)
        record("scroll", "PASS", "scrolled down 3 + up 3")
    except Exception as e:
        record("scroll", "FAIL", str(e))


def test_click_selector(ex: CDPExecutor):
    print(SEP)
    print("TEST 8 — Click by CSS Selector")
    print("  (navigating to a known test page with radio buttons)")
    try:
        # Use a local data URI with a radio button — no external dependency
        html = (
            "data:text/html,<html><body>"
            "<input type='radio' name='q' value='yes' id='r1'> Yes"
            "<input type='radio' name='q' value='no'  id='r2'> No"
            "</body></html>"
        )
        ex.eval_js(f"window.location.href = '{html}'")
        time.sleep(1.0)
        ex.click_selector("#r1")
        checked = ex.eval_js("document.getElementById('r1').checked")
        if checked:
            record("click_selector", "PASS", "#r1 checked after CDP click")
        else:
            record("click_selector", "FAIL", "#r1 not checked — click may have missed")
    except Exception as e:
        record("click_selector", "FAIL", str(e))


def test_click_js(ex: CDPExecutor):
    print(SEP)
    print("TEST 9 — Click by JS Expression")
    try:
        ex.click_js('document.getElementById("r2")')
        checked = ex.eval_js("document.getElementById('r2').checked")
        if checked:
            record("click_js", "PASS", "#r2 checked via click_js")
        else:
            record("click_js", "FAIL", "#r2 not checked")
    except Exception as e:
        record("click_js", "FAIL", str(e))


def test_type_text(ex: CDPExecutor):
    print(SEP)
    print("TEST 10 — Type Text")
    try:
        html = (
            "data:text/html,<html><body>"
            "<input type='text' id='t1'>"
            "</body></html>"
        )
        ex.eval_js(f"window.location.href = '{html}'")
        time.sleep(1.0)
        ex.click_selector("#t1")
        ex.type_text("hello cdp")
        val = ex.eval_js("document.getElementById('t1').value")
        if val == "hello cdp":
            record("type_text", "PASS", f"value = {val!r}")
        else:
            record("type_text", "FAIL", f"expected 'hello cdp', got {val!r}")
    except Exception as e:
        record("type_text", "FAIL", str(e))


# ── Main ──────────────────────────────────────────────────────────────────────

def main():
    print("=== CareerBridge CDP Test Suite ===\n")

    port = test_port_discovery()
    if not port:
        print("\n[ABORT] Cannot proceed without a CDP port. Run ixbrowser_cdp_inject.py first.")
        _print_summary()
        sys.exit(1)

    ex = CDPExecutor()
    if not test_connect(ex):
        print("\n[ABORT] Connection failed.")
        _print_summary()
        sys.exit(1)

    test_page_info(ex)
    test_eval_js(ex)
    test_axtree(ex)
    test_dom_interactives(ex)
    test_scroll(ex)
    test_click_selector(ex)
    test_click_js(ex)
    test_type_text(ex)

    ex.disconnect()
    _print_summary()


def _print_summary():
    print("\n" + SEP)
    print("SUMMARY")
    print(SEP)
    passed  = [r for r in results if r[1] == "PASS"]
    failed  = [r for r in results if r[1] == "FAIL"]
    skipped = [r for r in results if r[1] == "SKIP"]
    print(f"  PASS:  {len(passed)}")
    print(f"  FAIL:  {len(failed)}")
    print(f"  SKIP:  {len(skipped)}")
    if failed:
        print("\nFailed tests:")
        for name, _, detail in failed:
            print(f"  ✗ {name}: {detail}")
    if skipped:
        print("\nSkipped (manual step needed):")
        for name, _, detail in skipped:
            print(f"  ~ {name}: {detail}")


if __name__ == "__main__":
    main()
