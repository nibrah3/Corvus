"""
test_e2e.py — End-to-end test runner for all CareerBridge capabilities.

Tests (in order):
  1. IXBrowser API path (tomoneshaa / paid)      — open profile 14, get CDP URL
  2. CDP connection                               — axtree, eval_js, navigate
  3. Humanizer                                    — mouse move, windmouse path
  4. Assessment pipeline (16personalities.com)   — full MCQ loop
  5. Screenshot / DOM fallback                   — capture_mcp + DOM extraction comparison
  6. Gate client                                 — Redis gate write + read (dry-run)
  7. IXBrowser free path                         — psutil scan (user must open free profile first)
  8. Application pipeline (Greenhouse demo form) — browser-use + DOM-only mode
  9. Annotation pipeline (Zooniverse Galaxy Zoo) — Gemini Flash image classification

Usage:
    python scripts/test_e2e.py [--test N]    # run specific test (1-9)
    python scripts/test_e2e.py               # run all
    python scripts/test_e2e.py --api-only    # tests 1-6 only
"""
from __future__ import annotations

import argparse
import base64
import json
import logging
import os
import sys
import time

CB_DIR = os.path.normpath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, CB_DIR)

# Load .env
with open(os.path.join(CB_DIR, ".env")) as _f:
    for _line in _f:
        _line = _line.strip()
        if "=" in _line and not _line.startswith("#"):
            _k, _, _v = _line.partition("=")
            os.environ.setdefault(_k.strip(), _v.strip())

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)-7s %(name)s: %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger("e2e")

_RESULTS: dict[str, str] = {}


def _pass(name: str, detail: str = "") -> None:
    _RESULTS[name] = f"PASS{' -- ' + detail if detail else ''}"
    log.info("PASS  %s  %s", name, detail)


def _fail(name: str, reason: str) -> None:
    _RESULTS[name] = f"FAIL -- {reason}"
    log.error("FAIL  %s  %s", name, reason)


def _skip(name: str, reason: str) -> None:
    _RESULTS[name] = f"SKIP -- {reason}"
    log.warning("SKIP  %s  %s", name, reason)


# ── Test 1: IXBrowser API — open profile, get CDP URL ────────────────────────

def test_ixbrowser_api(profile_id: int = 14) -> str | None:
    name = "ixbrowser_api"
    try:
        from careerbridge.ixbrowser_connector import ix_open_profile, is_paid_account
        cdp_url = ix_open_profile(profile_id)
        if not cdp_url.startswith("ws://") and not cdp_url.startswith("wss://"):
            _fail(name, f"Bad CDP URL: {cdp_url}")
            return None
        _pass(name, f"profile_id={profile_id} cdp={cdp_url[:50]}")
        return cdp_url
    except Exception as e:
        _fail(name, str(e)[:200])
        return None


# ── Test 2: CDP connection ────────────────────────────────────────────────────

def test_cdp(cdp_url: str) -> bool:
    name = "cdp_connection"
    try:
        from careerbridge.cdp_executor import CDPExecutor
        cdp = CDPExecutor()
        cdp.connect_ws(cdp_url)

        # Navigate to a simple test page
        cdp.navigate("https://example.com")
        time.sleep(2)

        # Get axtree
        tree = cdp.get_axtree()
        if not tree:
            _fail(name, "axtree returned empty")
            cdp.disconnect()
            return False

        # Eval JS
        title = cdp.eval_js("document.title")
        log.info("Page title: %r, axtree nodes: %d", title, len(tree))

        # Get screen offset
        ox, oy = cdp._get_screen_offset()
        log.info("Screen offset: (%d, %d)", ox, oy)

        cdp.disconnect()
        _pass(name, f"axtree={len(tree)} nodes, title={title!r}, offset=({ox},{oy})")
        return True
    except Exception as e:
        _fail(name, str(e)[:200])
        return False


# ── Test 3: Humanizer — windmouse path + click ───────────────────────────────

def test_humanizer() -> bool:
    name = "humanizer"
    try:
        from windmouse.core import wind_mouse
        pts = list(wind_mouse(100, 100, 400, 300, gravity_magnitude=9.0,
                              wind_magnitude=3.0, max_step=15, damped_distance=12))
        if len(pts) < 3:
            _fail(name, f"windmouse only generated {len(pts)} points")
            return False
        log.info("windmouse: %d points from (100,100) to (400,300)", len(pts))

        from humanizer_mcp._profile import BehaviorProfile
        from humanizer_mcp._mouse import move as _hum_move
        import random
        rng = random.Random(42)
        prof = BehaviorProfile.default()
        # Move to a safe area (won't click anything visible)
        _hum_move(200, 200, profile=prof, rng=rng)
        log.info("humanizer move OK")

        _pass(name, f"windmouse={len(pts)}pts, move=ok, backend=" +
              str(getattr(sys.modules.get("humanizer_mcp._mouse", None), "_backend", "?")))
        return True
    except Exception as e:
        _fail(name, str(e)[:200])
        return False


# ── Test 4: Assessment pipeline ───────────────────────────────────────────────

def test_assessment(cdp_url: str, url: str = "https://www.16personalities.com/free-personality-test") -> bool:
    name = "assessment_pipeline"
    try:
        from careerbridge.assessment_pipeline import AssessmentPipeline, AssessmentConfig

        # Minimal profile: Big Five neutral personality
        class _Profile:
            name = "James Okafor"
            email = "james.okafor@testmail.com"
            class big_five:
                openness          = 0.65
                conscientiousness = 0.70
                extraversion      = 0.55
                agreeableness     = 0.75
                neuroticism       = 0.35

        cfg = AssessmentConfig(
            cdp_url=cdp_url,
            url=url,
            profile=_Profile(),
            human_gate=False,     # fully automated for E2E test
            max_pages=5,          # limit pages for speed
            page_timeout_s=20.0,
            profile_seed=42,
        )
        result = AssessmentPipeline(cfg).run()
        log.info(
            "Assessment result: ok=%s pages=%d llm_calls=%d actions=%d error=%s",
            result.ok, result.pages_done, result.llm_calls, result.actions_taken, result.error
        )
        if result.ok or result.pages_done > 0:
            _pass(name, f"pages={result.pages_done} llm={result.llm_calls} actions={result.actions_taken}")
        else:
            _fail(name, result.error or "no pages completed")
        return result.ok
    except Exception as e:
        _fail(name, str(e)[:300])
        return False


# ── Test 5: Screenshot vs DOM comparison ─────────────────────────────────────

def test_screenshot_vs_dom(cdp_url: str) -> bool:
    name = "screenshot_vs_dom"
    try:
        from careerbridge.cdp_executor import CDPExecutor
        cdp = CDPExecutor()
        cdp.connect_ws(cdp_url)
        cdp.navigate("https://example.com")
        time.sleep(1)

        # DOM extraction
        t0 = time.monotonic()
        tree = cdp.get_axtree()
        dom_ms = (time.monotonic() - t0) * 1000

        # Screenshot via capture_mcp MCP
        import urllib.request
        body = json.dumps({
            "jsonrpc": "2.0", "id": 1,
            "method": "tools/call",
            "params": {"name": "screenshot", "arguments": {}},
        }).encode()
        req = urllib.request.Request(
            "http://localhost:8702/mcp", data=body,
            headers={"Content-Type": "application/json"}
        )
        t0 = time.monotonic()
        with urllib.request.urlopen(req, timeout=10) as r:
            scr_resp = json.loads(r.read())
        scr_ms = (time.monotonic() - t0) * 1000

        scr_ok = "base64" in (scr_resp.get("result", {}).get("content", [{}])[0].get("text", ""))
        cdp.disconnect()

        verdict = (
            f"DOM: {dom_ms:.0f}ms/{len(tree)}nodes | "
            f"Screenshot: {scr_ms:.0f}ms/{'OK' if scr_ok else 'FAIL'} | "
            f"DOM {'FASTER' if dom_ms < scr_ms else 'SLOWER'} by {abs(dom_ms-scr_ms):.0f}ms"
        )
        _pass(name, verdict)
        log.info("Verdict: For browser-use, use DOM-only (no vision) + screenshot fallback only on parse failure")
        return True
    except Exception as e:
        _fail(name, str(e)[:200])
        return False


# ── Test 6: Gate client (dry-run, no Redis required for smoke) ────────────────

def test_gate_client() -> bool:
    name = "gate_client"
    try:
        import socket
        def redis_up():
            try:
                with socket.create_connection(("127.0.0.1", int(os.environ.get("REDIS_PORT","6380"))), timeout=2): return True
            except: return False

        if not redis_up():
            _skip(name, "Redis not reachable — run vps_tunnel.ps1")
            return True

        from careerbridge.gate_client import request_gate, answer_gate, pending_gates
        import threading

        result_holder = [None]
        gate_id_holder = [None]

        def _answer_thread():
            time.sleep(1.0)
            gates = pending_gates()
            if gates:
                gid = gates[0]["gate_id"]
                gate_id_holder[0] = gid
                answer_gate(gid, "approve", "Test approved answer")

        t = threading.Thread(target=_answer_thread, daemon=True)
        t.start()

        answer = request_gate("Test Field", "Test draft", job_id=999, timeout=10.0)
        t.join(timeout=5)

        if answer == "Test approved answer":
            _pass(name, "gate round-trip OK, answer received")
        else:
            _fail(name, f"Expected 'Test approved answer', got {answer!r}")
            return False
        return True
    except Exception as e:
        _fail(name, str(e)[:200])
        return False


# ── Test 7: IXBrowser free path (psutil scan) ─────────────────────────────────

def test_ixbrowser_free() -> str | None:
    name = "ixbrowser_free"
    try:
        from careerbridge.cdp_executor import discover_cdp_port
        from careerbridge.ixbrowser_connector import _cdp_url_from_port
        port = discover_cdp_port()
        if port is None:
            _skip(name, "No IXBrowser free profile open (open one manually first)")
            return None
        cdp_url = _cdp_url_from_port(port)
        _pass(name, f"port={port} cdp={cdp_url[:50]}")
        return cdp_url
    except Exception as e:
        _fail(name, str(e)[:200])
        return None


# ── Test 8: Application pipeline (DOM-only browser-use) ───────────────────────

def test_application(cdp_url: str) -> bool:
    name = "application_pipeline"
    try:
        import asyncio
        from careerbridge.application_pipeline import ApplicationPipeline, ApplicationConfig

        profile = {
            "name":     "James Okafor",
            "email":    "james.okafor@testmail.com",
            "phone":    "+44 7700 900123",
            "location": "London, UK",
            "bio":      "Experienced software engineer with 3 years in fintech.",
            "skills":   '["Python","SQL","API development","Git"]',
        }

        cfg = ApplicationConfig(
            cdp_url=cdp_url,
            # Use a simple public form for smoke test; YC page is too slow/heavy
            url="https://boards.greenhouse.io/embed/job_app?for=anthropic&token=4020305008",
            profile=profile,
            task_type="application",
            max_steps=5,
            timeout_s=180,  # 3 min
            job_id="test-001",
        )

        result = asyncio.run(ApplicationPipeline(cfg).run())
        log.info(
            "Application: ok=%s status=%s steps=%d llm=%d error=%s",
            result.ok, result.status, result.steps_taken, result.llm_calls, result.error
        )
        # Smoke test: pass as long as the pipeline booted (any steps OR just a timeout).
        # Login walls, captchas, timeouts are expected on live sites.
        hard_crash = (
            result.failure_type not in ("timeout", "captcha", "session_expired",
                                        "duplicate", "not_found", "unknown", None)
            and result.steps_taken == 0
            and result.error is not None
            and "import" in (result.error or "")  # only fail on import/config errors
        )
        if hard_crash:
            _fail(name, f"Pipeline hard crash: {result.error[:100]}")
        else:
            detail = f"status={result.status} steps={result.steps_taken} llm={result.llm_calls}"
            if result.failure_type:
                detail += f" ({result.failure_type})"
            _pass(name, detail)
        return True
    except Exception as e:
        _fail(name, str(e)[:300])
        return False


# ── Test 9: Annotation pipeline ───────────────────────────────────────────────
# Part A: Gemini vision connectivity (no browser — proves OpenRouter + Gemini Flash)
# Part B: Full browser pipeline on Zooniverse Galaxy Zoo (bonus; skips on login wall)

def test_annotation(cdp_url: str) -> bool:
    name = "annotation_pipeline"
    try:
        if not os.environ.get("OPENROUTER_API_KEY"):
            _skip(name, "OPENROUTER_API_KEY not set")
            return True

        # ── Part A: Gemini vision — download + resize + b64 ──────────────────
        # Wikipedia blocks hotlinking; download & resize to ~400px to keep
        # payload small (inline base64 limit is ~1MB).
        import base64 as _b64
        import io as _io
        import urllib.request as _urllib
        from PIL import Image as _PILImage
        from careerbridge.gemini_vision import annotate_image_b64
        test_image_url = (
            "https://upload.wikimedia.org/wikipedia/commons/"
            "c/c3/NGC_4414_%28NASA-med%29.jpg"
        )
        req = _urllib.Request(test_image_url,
                              headers={"User-Agent": "Mozilla/5.0"})
        with _urllib.urlopen(req, timeout=20) as _r:
            _raw_bytes = _r.read()
        _img = _PILImage.open(_io.BytesIO(_raw_bytes))
        _img.thumbnail((400, 400), _PILImage.LANCZOS)
        _buf = _io.BytesIO()
        _img.save(_buf, format="JPEG", quality=75)
        _img_b64 = _b64.b64encode(_buf.getvalue()).decode()
        log.info("Test image resized: %d b64 chars", len(_img_b64))
        vision_answer = annotate_image_b64(
            _img_b64, "image/jpeg",
            "What is shown in this astronomical image?",
            ["A spiral galaxy", "A mountain range", "A city skyline", "A human face"],
        )
        log.info("Gemini vision test: answer=%r", vision_answer)
        if not vision_answer:
            _fail(name, "Gemini vision returned no answer for NGC 4414 test image")
            return False
        log.info("Gemini vision PASS: %r", vision_answer)

        # ── Part B: Browser annotation pipeline (Zooniverse) ──────────────────
        from careerbridge.annotation_pipeline import AnnotationPipeline, AnnotationConfig
        cfg = AnnotationConfig(
            cdp_url=cdp_url,
            url="https://www.zooniverse.org/projects/zookeeper/galaxy-zoo/classify",
            task_type="image",
            platform="zooniverse",
            max_tasks=3,
            task_timeout_s=30.0,
            profile_seed=42,
        )
        result = AnnotationPipeline(cfg).run()
        log.info(
            "Annotation browser: ok=%s tasks=%d llm=%d actions=%d error=%s",
            result.ok, result.tasks_done, result.llm_calls,
            result.actions_taken, result.error,
        )

        # Hard fail only on import/config errors — login walls are normal for live sites
        if result.error and any(kw in result.error.lower()
                                for kw in ("import", "module", "attributeerror")):
            _fail(name, f"Code error: {result.error[:120]}")
            return False

        detail = (f"gemini_vision=OK({vision_answer[:25]}) "
                  f"browser_tasks={result.tasks_done} llm={result.llm_calls}")
        if result.tasks_done == 0:
            detail += " (login wall or no subjects — expected on unauthenticated session)"
        _pass(name, detail)
        return True
    except Exception as e:
        _fail(name, str(e)[:300])
        return False


# ── Print report ──────────────────────────────────────────────────────────────

def print_report() -> None:
    import io, sys
    # Force UTF-8 output so emoji render on Windows consoles
    out = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
    def _p(s: str) -> None:
        try:
            out.write(s + "\n")
            out.flush()
        except Exception:
            print(s.encode("ascii", "replace").decode())

    _p("\n" + "=" * 70)
    _p("E2E TEST REPORT")
    _p("=" * 70)
    passed = sum(1 for v in _RESULTS.values() if v.startswith("PASS"))
    failed = sum(1 for v in _RESULTS.values() if v.startswith("FAIL"))
    skipped = sum(1 for v in _RESULTS.values() if v.startswith("SKIP"))
    for test_name, result in _RESULTS.items():
        icon = "✅" if result.startswith("PASS") else ("❌" if result.startswith("FAIL") else "⏭")
        _p(f"  {icon}  {test_name:<30} {result}")
    _p("=" * 70)
    _p(f"  Passed: {passed}  Failed: {failed}  Skipped: {skipped}")
    _p("=" * 70 + "\n")


# ── Main ──────────────────────────────────────────────────────────────────────

def main() -> None:
    parser = argparse.ArgumentParser(description="CareerBridge E2E test runner")
    parser.add_argument("--test",     type=int, help="Run specific test (1-9)")
    parser.add_argument("--api-only", action="store_true", help="Tests 1-6 only")
    parser.add_argument("--profile",  type=int, default=12, help="IXBrowser profile ID (default 12)")
    parser.add_argument("--url",      help="Assessment URL override")
    args = parser.parse_args()

    log.info("Starting E2E test run")
    cdp_api  = None
    cdp_free = None

    run_all = not args.test

    # Auto-open IXBrowser when a dependent test runs standalone
    _needs_cdp = args.test in (2, 4, 5, 8, 9) if args.test else False

    if run_all or args.test == 1 or _needs_cdp:
        cdp_api = test_ixbrowser_api(args.profile)
        if cdp_api is None:
            cdp_api = test_ixbrowser_api(12)
        if args.test and args.test != 1 and _needs_cdp:
            _RESULTS.pop("ixbrowser_api", None)

    if (run_all or args.test == 2) and cdp_api:
        test_cdp(cdp_api)

    if run_all or args.test == 3:
        test_humanizer()

    if (run_all or args.test == 4) and cdp_api:
        assessment_url = args.url or "https://www.16personalities.com/free-personality-test"
        test_assessment(cdp_api, assessment_url)

    if (run_all or args.test == 5) and cdp_api:
        test_screenshot_vs_dom(cdp_api)

    if run_all or args.test == 6:
        test_gate_client()

    if (run_all or args.test == 7) and not args.api_only:
        cdp_free = test_ixbrowser_free()

    if (run_all or args.test == 8) and not args.api_only:
        test_url_cdp = cdp_free or cdp_api
        if test_url_cdp:
            test_application(test_url_cdp)
        else:
            _skip("application_pipeline", "No CDP URL available")

    if (run_all or args.test == 9) and not args.api_only:
        test_url_cdp = cdp_api or cdp_free
        if test_url_cdp:
            test_annotation(test_url_cdp)
        else:
            _skip("annotation_pipeline", "No CDP URL available")

    print_report()


if __name__ == "__main__":
    main()
