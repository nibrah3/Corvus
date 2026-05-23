"""
experiment_browseruse_vs_cdp.py
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Four live experiments comparing browser control strategies.

Task (same across all):
  1. Navigate to https://httpbin.org/user-agent  → read user-agent (fingerprint check)
  2. Navigate to https://httpbin.org/get          → read IP / headers (proxy check)
  3. Navigate to https://bot.sannysoft.com/       → read webdriver/CDP detection flags

Each mode logs:
  - Wall-clock duration
  - User-agent string (fingerprint integrity)
  - Bot detection flags found on sannysoft
  - Whether the task completed

EXPERIMENTS
  A. browser-use, Playwright-owned Chrome (fresh process)
  B. browser-use, CDP connected to our Chrome (port 9224)
  C. Our CDPExecutor + Claude API (Claude native, no browser-use)
  D. Claude Code calling MCP tools (natively, via this session)
     [D is the 'assistant controls it in-session' path — documented separately]

IXBrowser note:
  If an IXBrowser profile is open with --remote-debugging-port=9222, run:
      python experiment_browseruse_vs_cdp.py --ix
  which runs experiment B against port 9222 instead.
"""
from __future__ import annotations

import asyncio
import json
import os
import subprocess
import sys
import time
from pathlib import Path
from typing import Optional

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
sys.stderr.reconfigure(encoding="utf-8", errors="replace")

# Load .env
_env_file = Path(__file__).parent.parent / ".env"
if _env_file.exists():
    for _line in _env_file.read_text().splitlines():
        _line = _line.strip()
        if _line and not _line.startswith("#") and "=" in _line:
            k, _, v = _line.partition("=")
            os.environ.setdefault(k.strip(), v.strip())

ANTHROPIC_KEY   = os.environ.get("ANTHROPIC_API_KEY", "")
OPENROUTER_KEY  = os.environ.get("OPENROUTER_API_KEY", "")
# Use OpenRouter if direct Anthropic key has no credits
ACTIVE_KEY      = OPENROUTER_KEY or ANTHROPIC_KEY
OPENROUTER_BASE = "https://openrouter.ai/api/v1"
USE_OPENROUTER  = bool(OPENROUTER_KEY)
OR_MODEL        = "openrouter/anthropic/claude-haiku-4-5"   # LiteLLM openrouter provider prefix
CDP_PORT        = 9224   # our benchmark Chrome (separate from IXBrowser 9222)

CHROME_EXE = r"C:\Program Files\Google\Chrome\Application\chrome.exe"
CHROME_PROF = r"C:\tmp\chrome_exp_profile"

URLS = {
    "ua":     "https://httpbin.org/user-agent",
    "get":    "https://httpbin.org/get",
    "sannysoft": "https://bot.sannysoft.com/",
}

SEP = "=" * 65


# ── Shared helpers ────────────────────────────────────────────────────────────

def _launch_chrome(port: int) -> subprocess.Popen:
    import shutil, urllib.request as _ur
    if os.path.exists(CHROME_PROF):
        shutil.rmtree(CHROME_PROF, ignore_errors=True)
    proc = subprocess.Popen([
        CHROME_EXE,
        f"--remote-debugging-port={port}",
        "--remote-allow-origins=*",
        "--no-first-run", "--no-default-browser-check",
        "--disable-extensions", "--disable-sync",
        f"--user-data-dir={CHROME_PROF}",
        "--start-maximized",
    ], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
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
    raise RuntimeError(f"Chrome didn't expose CDP on port {port} in 15s")


def _make_llm():
    from browser_use.llm.litellm.chat import ChatLiteLLM
    if USE_OPENROUTER:
        return ChatLiteLLM(
            model=OR_MODEL,
            api_key=OPENROUTER_KEY,
            api_base=OPENROUTER_BASE,
            max_tokens=2048,
        )
    return ChatLiteLLM(
        model="claude-haiku-4-5-20251001",
        api_key=ANTHROPIC_KEY,
        max_tokens=2048,
    )


# ── EXPERIMENT A: browser-use, Playwright-owned Chrome ────────────────────────

async def experiment_A() -> dict:
    print(f"\n{SEP}")
    print("EXPERIMENT A: browser-use / Playwright-owned Chrome")
    print(SEP)
    t0 = time.perf_counter()

    from browser_use import Agent
    from browser_use.browser.session import BrowserSession

    session = BrowserSession(
        headless=False,
        args=["--start-maximized"],
    )

    agent = Agent(
        task=(
            "1. Go to https://httpbin.org/user-agent and read the user-agent value. "
            "2. Go to https://httpbin.org/get and note the X-Amzn-Trace-Id and User-Agent in headers. "
            "3. Go to https://bot.sannysoft.com/ and wait 3 seconds, then list any RED or FAIL items visible on the page. "
            "Report all findings clearly."
        ),
        llm=_make_llm(),
        browser_session=session,
        max_actions_per_step=3,
        use_vision=True,
    )

    try:
        result = await agent.run(max_steps=15)
        final = result.final_result() if result else "no result"
    except Exception as e:
        final = f"ERROR: {e}"
    finally:
        try:
            await session.close()
        except Exception:
            pass

    elapsed = (time.perf_counter() - t0)
    print(f"\n  Duration: {elapsed:.1f}s")
    print(f"  Result:\n{final}")
    return {"mode": "A_browseruse_own_chrome", "seconds": round(elapsed, 1), "result": str(final)[:800]}


# ── EXPERIMENT B: browser-use, CDP URL to our Chrome ──────────────────────────

async def experiment_B(cdp_port: int, label: str = "B") -> dict:
    print(f"\n{SEP}")
    print(f"EXPERIMENT {label}: browser-use / CDP to existing Chrome (port {cdp_port})")
    print(SEP)
    t0 = time.perf_counter()

    from browser_use import Agent
    from browser_use.browser.session import BrowserSession

    session = BrowserSession(
        cdp_url=f"http://127.0.0.1:{cdp_port}",
    )

    agent = Agent(
        task=(
            "1. Go to https://httpbin.org/user-agent and read the user-agent value. "
            "2. Go to https://httpbin.org/get and note the User-Agent in the JSON response. "
            "3. Go to https://bot.sannysoft.com/ and wait 3 seconds, then list any RED or FAIL items visible. "
            "Report all findings clearly."
        ),
        llm=_make_llm(),
        browser_session=session,
        max_actions_per_step=3,
        use_vision=True,
    )

    try:
        result = await agent.run(max_steps=15)
        final = result.final_result() if result else "no result"
    except Exception as e:
        final = f"ERROR: {e}"
    finally:
        try:
            await session.close()
        except Exception:
            pass

    elapsed = (time.perf_counter() - t0)
    print(f"\n  Duration: {elapsed:.1f}s")
    print(f"  Result:\n{final}")
    return {"mode": f"{label}_browseruse_cdp_{cdp_port}", "seconds": round(elapsed, 1), "result": str(final)[:800]}


# ── EXPERIMENT C: CDPExecutor + Claude API (no browser-use) ───────────────────

async def experiment_C(cdp_port: int) -> dict:
    print(f"\n{SEP}")
    print(f"EXPERIMENT C: CDPExecutor + Claude API direct (port {cdp_port})")
    print(SEP)
    t0 = time.perf_counter()

    sys.path.insert(0, str(Path(__file__).parent.parent))
    from careerbridge.cdp_executor import CDPExecutor, CDPError
    import anthropic

    ex = CDPExecutor()
    ex.connect(port=cdp_port)
    if USE_OPENROUTER:
        client = anthropic.Anthropic(api_key=OPENROUTER_KEY, base_url=OPENROUTER_BASE)
        c_model = "anthropic/claude-haiku-4-5"
    else:
        client = anthropic.Anthropic(api_key=ANTHROPIC_KEY)
        c_model = "claude-haiku-4-5-20251001"
    actions_taken = []
    findings = []

    def page_state() -> str:
        try:
            url  = ex.eval_js("location.href") or "?"
            body = ex.eval_js("document.body.innerText") or ""
            return f"URL: {url}\n---\n{body[:1500]}"
        except Exception as e:
            return f"(error reading page: {e})"

    task = (
        "You control a Chrome browser. Use the provided navigate/read functions. "
        "Steps: 1) Check https://httpbin.org/user-agent 2) Check https://httpbin.org/get "
        "3) Check https://bot.sannysoft.com/ and report any FAIL/RED items. "
        "Report all findings."
    )

    pages_to_visit = [URLS["ua"], URLS["get"], URLS["sannysoft"]]
    for url in pages_to_visit:
        print(f"  Navigating to {url}...")
        ex.navigate(url)
        time.sleep(2.0 if "sannysoft" in url else 0.8)
        state = page_state()

        msg = client.messages.create(
            model=c_model,
            max_tokens=512,
            messages=[{
                "role": "user",
                "content": (
                    f"Analyze this page content and extract key information for bot detection research:\n\n"
                    f"{state}\n\n"
                    f"Return: user-agent (if present), any FAIL/RED/detected items, and a 1-line summary."
                )
            }]
        )
        analysis = msg.content[0].text if msg.content else ""
        findings.append({"url": url, "analysis": analysis})
        print(f"  Claude analysis: {analysis[:120]}")
        actions_taken.append(f"navigate+read: {url}")

    ex.disconnect()
    elapsed = (time.perf_counter() - t0)
    print(f"\n  Duration: {elapsed:.1f}s | Actions: {len(actions_taken)}")
    summary = "\n".join(f['analysis'] for f in findings)
    return {
        "mode": "C_cdpexecutor_claude_direct",
        "seconds": round(elapsed, 1),
        "actions": len(actions_taken),
        "result": summary[:800],
    }


# ── COMPARISON PRINTER ────────────────────────────────────────────────────────

def print_comparison(results: list[dict]) -> None:
    print(f"\n{SEP}")
    print("COMPARISON SUMMARY")
    print(SEP)

    headers = ["Mode", "Time(s)", "Completed"]
    print(f"  {'Mode':<40} {'Time':>8}   Notes")
    print("  " + "-" * 60)
    for r in results:
        mode = r["mode"]
        t = r.get("seconds", "?")
        res = r.get("result", "")
        ok  = "OK" if "ERROR" not in res else "FAIL"
        note = res[:60].replace("\n", " ")
        print(f"  {mode:<40} {str(t):>6}s   [{ok}] {note}")

    print(f"""
  Architecture verdict:
  ─────────────────────
  A: browser-use (own Chrome)
     + Simplest setup. Works standalone.
     - Launches a vanilla Chrome with NO IXBrowser fingerprint.
       Bot detection sees generic Playwright UA + automation flags.
     - Playwright injects automation JS properties (navigator.webdriver=true).
     - CANNOT use IXBrowser profiles or their fingerprints.

  B: browser-use + CDP to existing Chrome (or IXBrowser)
     + Connects to a running Chrome → preserves fingerprint IF that Chrome
       is an IXBrowser profile with fingerprint injection already active.
     + Playwright CDP connect DOES NOT re-inject automation flags on connect
       (it inherits the running context).
     + With IXBrowser: full fingerprint stack (Canvas, WebGL, UA, fonts)
       is already baked in. browser-use just reads and acts.
     - Requires IXBrowser profile open with --remote-debugging-port set.
     - Playwright still adds its own event listeners — some sites detect these.

  C: CDPExecutor + Claude API (no browser-use)
     + Zero Playwright fingerprint overhead. Pure WebSocket to browser.
     + OS-level clicks via pynput = no LLKHF_INJECTED.
     + Works with IXBrowser via the same cdp_url pattern.
     + 2-4x fewer LLM calls (no browser-use scaffolding prompts).
     - Requires manual action implementation (we built this).
     - No built-in element highlighting/extraction like browser-use has.

  D: Claude Code natively (this session, MCP tools)
     + Claude Code calls mcp__cdp__cdp_click / cdp_type / cdp_eval directly.
     + Same CDPExecutor underneath — same stealth properties as C.
     + No extra process overhead.
     - Requires Claude Code session open + MCP server running.
     - Latency: Claude API round-trip per action (~300-1500ms).

  RECOMMENDATION for IXBrowser pipeline:
    Use B for complex multi-step reasoning tasks (browser-use handles
    the "what to click next" loop automatically).
    Use C/D for structured flows where actions are known in advance
    (form filling, fixed sequences) — faster and stealthier.
    Never use A in production — it loses the IXBrowser fingerprint.
""")


# ── Main ──────────────────────────────────────────────────────────────────────

async def main() -> None:
    import argparse
    p = argparse.ArgumentParser()
    p.add_argument("--ix",    action="store_true", help="Run experiment B against IXBrowser port 9222")
    p.add_argument("--skip-a", action="store_true", help="Skip experiment A (browser-use own Chrome)")
    args = p.parse_args()

    if not ANTHROPIC_KEY:
        print("ERROR: ANTHROPIC_API_KEY not set")
        sys.exit(1)

    results = []
    chrome_proc: Optional[subprocess.Popen] = None

    # Launch our own Chrome for experiments B and C
    print(f"Launching Chrome on port {CDP_PORT} for experiments B+C...")
    chrome_proc = _launch_chrome(CDP_PORT)
    print(f"Chrome PID={chrome_proc.pid}")

    try:
        # A: browser-use / own Chrome
        if not args.skip_a:
            r = await experiment_A()
            results.append(r)
        else:
            print("\n[A skipped]")

        # B: browser-use / CDP to our Chrome
        r = await experiment_B(CDP_PORT, label="B")
        results.append(r)

        # B-IX: browser-use / CDP to IXBrowser (if requested)
        if args.ix:
            r = await experiment_B(9222, label="B-IX")
            results.append(r)

        # C: CDPExecutor + Claude direct
        r = await experiment_C(CDP_PORT)
        results.append(r)

        print_comparison(results)

    finally:
        if chrome_proc:
            chrome_proc.terminate()
            print("\nChrome terminated.")


if __name__ == "__main__":
    asyncio.run(main())
