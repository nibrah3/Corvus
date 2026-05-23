"""
queue_bridge.py - Desktop application dispatcher.

Polls corvus:approved_jobs Redis queue. For each job:
  1. Fetches profile and job details from VPS postgres (via vps_mcp SSH tunnel)
  2. Generates a tailored CV locally (cv_generator.py + reportlab)
  3. Opens the candidate's IXBrowser profile via local API (port 53200)
  4. Runs browser-use LLM agent (3-LLM: workhorse + vision + reasoning) to fill the form
  5. Updates job status in VPS postgres

Requirements:
  - IXBrowser must be running and have profiles named to match postgres profile IDs
  - VPS SSH tunnels active (Redis:6380, Postgres:5433) -- run vps_tunnel.ps1
  - vps_mcp running on localhost:8713 -- run start_mcps.ps1
  - E:\\cb-core\\.env must contain OPENROUTER_API_KEY

Usage:
  python scripts/queue_bridge.py [--once]
  python scripts/queue_bridge.py --list-profiles
"""
from __future__ import annotations

import argparse
import asyncio
import json
import logging
import os
import socket
import sys
import time
import urllib.request
from pathlib import Path

CB_DIR = Path(__file__).resolve().parent.parent

# ── Config ──────────────────────────────────────────────────────────────────────

def _load_env():
    env_path = CB_DIR / ".env"
    if env_path.exists():
        for line in env_path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, _, v = line.partition("=")
                os.environ.setdefault(k.strip(), v.strip())

_load_env()

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger(__name__)

REDIS_HOST      = "127.0.0.1"
REDIS_PORT      = 6380  # SSH tunnel to VPS Redis
APPROVED_KEY    = "corvus:approved_jobs"
RESULTS_KEY     = "corvus:job_results"
POLL_INTERVAL   = 15

VPS_MCP_URL     = "http://localhost:8713/mcp"
IX_API_BASE     = "http://127.0.0.1:53200/api/v2"
CV_DIR          = CB_DIR / "cvs"

OPENROUTER_KEY      = os.environ.get("OPENROUTER_API_KEY", "")
OPENROUTER_BASE_URL = os.environ.get("OPENROUTER_BASE_URL", "https://openrouter.ai/api/v1")

# 3-LLM architecture (matches VPS browser-use container)
MODEL_WORKHORSE = os.environ.get("OPENROUTER_MODEL_WORKHORSE",
                                  os.environ.get("OPENROUTER_MODEL", "anthropic/claude-haiku-4-5"))
MODEL_VISION    = os.environ.get("OPENROUTER_MODEL_VISION",    "openai/gpt-4o-mini")
MODEL_REASONING = os.environ.get("OPENROUTER_MODEL_REASONING", "openai/gpt-4o-mini")

TASK_TIMEOUT    = int(os.environ.get("TASK_TIMEOUT_SECONDS", "3600"))
MAX_STEPS       = int(os.environ.get("MAX_STEPS", "50"))

_TAB_CONSTRAINT = (
    "CRITICAL BROWSER RULES (must follow at all times):\n"
    "- Stay on task. Follow wherever the site navigates you -- new tabs, redirects.\n"
    "- Do NOT open new tabs to search for answers or visit external sites.\n"
    "- When entering text: click the field first, then type.\n"
)

# ── LLM factory ─────────────────────────────────────────────────────────────────

def _make_llm(model: str):
    from browser_use.llm.litellm.chat import ChatLiteLLM
    if not model.startswith("openrouter/"):
        model = f"openrouter/{model}"
    return ChatLiteLLM(
        model=model,
        api_key=OPENROUTER_KEY,
        api_base=OPENROUTER_BASE_URL,
        temperature=0.0,
    )

# ── Redis helpers ────────────────────────────────────────────────────────────────

def _redis_cmd(*parts: str) -> bytes:
    with socket.create_connection((REDIS_HOST, REDIS_PORT), timeout=5) as sock:
        cmd = f"*{len(parts)}\r\n" + "".join(f"${len(p)}\r\n{p}\r\n" for p in parts)
        sock.sendall(cmd.encode())
        data = b""
        while True:
            chunk = sock.recv(4096)
            if not chunk:
                break
            data += chunk
            if b"\r\n" in data:
                break
        return data


def _lpop(key: str) -> str | None:
    try:
        reply = _redis_cmd("LPOP", key).decode(errors="replace").strip()
        if reply in ("$-1", "*-1") or reply == "-1":
            return None
        lines = reply.split("\r\n")
        if lines[0].startswith("$") and len(lines) > 1:
            return lines[1]
        return None
    except Exception:
        return None


def _rpush(key: str, value: str) -> None:
    try:
        _redis_cmd("RPUSH", key, value)
    except Exception:
        pass


# ── VPS MCP helper ───────────────────────────────────────────────────────────────

_mcp_seq = 0


def _mcp_call(tool: str, **kwargs) -> dict:
    global _mcp_seq
    _mcp_seq += 1
    body = json.dumps({
        "jsonrpc": "2.0", "id": _mcp_seq,
        "method": "tools/call",
        "params": {"name": tool, "arguments": kwargs},
    }).encode()
    req = urllib.request.Request(VPS_MCP_URL, data=body,
                                  headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=45) as r:
            resp = json.loads(r.read())
        content = resp["result"]["content"][0]["text"]
        return json.loads(content)
    except Exception as e:
        return {"error": str(e)}


# ── CV generation (local) ────────────────────────────────────────────────────────

def _generate_cv(profile: dict, job: dict) -> dict | None:
    try:
        sys.path.insert(0, str(CB_DIR))
        from cv_generator import generate_cv
        CV_DIR.mkdir(parents=True, exist_ok=True)
        return generate_cv(profile, job, out_dir=str(CV_DIR))
    except Exception as e:
        logger.warning(f"CV generation failed: {e}")
        return None


# ── Persona block ────────────────────────────────────────────────────────────────

def _build_persona(profile: dict) -> str:
    parts = []
    name  = profile.get("name", "")
    bio   = (profile.get("bio") or "")[:500]
    skills = profile.get("skills") or "[]"
    try:
        skill_list = json.loads(skills) if isinstance(skills, str) else skills
        skills_str = ", ".join(skill_list[:20]) if skill_list else ""
    except Exception:
        skills_str = str(skills)[:200]

    exp = profile.get("experience") or "[]"
    try:
        exp_list = json.loads(exp) if isinstance(exp, str) else exp
        exp_lines = []
        for e in (exp_list or [])[:4]:
            if isinstance(e, dict):
                exp_lines.append(
                    f"  - {e.get('role','')} at {e.get('company','')} "
                    f"({e.get('years', e.get('duration', ''))})"
                )
        exp_str = "\n".join(exp_lines)
    except Exception:
        exp_str = ""

    if name:
        parts.append(f"Name: {name}")
    if bio:
        parts.append(f"Background: {bio}")
    if skills_str:
        parts.append(f"Skills: {skills_str}")
    if exp_str:
        parts.append(f"Experience:\n{exp_str}")

    big_five = profile.get("big_five")
    if big_five:
        try:
            bf = json.loads(big_five) if isinstance(big_five, str) else big_five
            traits = ", ".join(f"{k}={v}" for k, v in (bf or {}).items())
            if traits:
                parts.append(f"Personality: {traits}")
        except Exception:
            pass

    return "\n".join(parts)


# ── Task prompt builder ───────────────────────────────────────────────────────────

def _build_task_prompt(base_task: str, persona: str, task_type: str = "application",
                       pre_answers: str = "") -> str:
    persona_block = ""
    if persona:
        persona_block = (
            f"You are completing this task as the following candidate:\n{persona}\n\n"
            "Write all prose/text responses in that candidate's natural voice and from their "
            "perspective.\n\n"
        )

    if task_type in ("quiz", "mcq", "assessment"):
        reasoning = (
            "For each question you encounter:\n"
            "1. Read the question and ALL answer options carefully.\n"
            "2. Think through which answer is correct before clicking.\n"
            "3. Only then select your answer.\n\n"
        )
    else:
        reasoning = ""

    prompt = f"{_TAB_CONSTRAINT}\n{persona_block}{reasoning}{base_task}"

    if pre_answers:
        prompt += (
            "\n\n=== PRE-REASONED ANSWERS (use these exactly) ===\n"
            f"{pre_answers}\n"
            "Navigate to each question and type/select the corresponding answer."
        )

    return prompt


# ── Claude pre-answer generation ────────────────────────────────────────────────

async def _pregenerate_answers(page_text: str, task_description: str) -> str:
    try:
        import litellm as ll
        model = MODEL_REASONING
        if not model.startswith("openrouter/"):
            model = f"openrouter/{model}"
        resp = await ll.acompletion(
            model=model,
            api_key=OPENROUTER_KEY,
            api_base=OPENROUTER_BASE_URL,
            messages=[{"role": "user", "content": (
                f"You are helping complete an online assessment. Here is the current page content:\n\n"
                f"{page_text[:4000]}\n\n"
                f"Task context: {task_description}\n\n"
                "Identify every question or fill-in-the-blank on this page. "
                "For each one, provide the correct answer. "
                "Format your response as a numbered list:\n"
                "1. [exact answer for question 1]\n"
                "2. [exact answer for question 2]\n"
                "Only the answers -- no explanations."
            )}],
            max_tokens=800,
            temperature=0.0,
        )
        answers = resp.choices[0].message.content.strip()
        # Strip preambles
        lower = answers.lower()
        for pre in ("here are the answers", "sure,", "of course,", "the answers are"):
            if lower.startswith(pre):
                idx = answers.find("1.")
                if idx > 0:
                    answers = answers[idx:].strip()
                break
        logger.info(f"Pre-answers generated: {len(answers)} chars")
        return answers
    except Exception as e:
        logger.warning(f"Pre-answer generation failed (non-fatal): {e}")
        return ""


# ── IXBrowser local API (port 53200) ─────────────────────────────────────────────

def ix_running() -> bool:
    try:
        with socket.create_connection(("127.0.0.1", 53200), timeout=2):
            return True
    except Exception:
        return False


def ix_list_profiles() -> list:
    from ixbrowser_local_api import IXBrowserClient
    client = IXBrowserClient()
    return client.get_profile_list(limit=100) or []


def ix_find_profile(postgres_profile_id: str) -> int:
    """Return IXBrowser profile_id (int) matching the postgres profile_id."""
    defaults_path = CB_DIR / "defaults.json"
    try:
        defaults = json.loads(defaults_path.read_text())
        mapping = defaults.get("ixbrowser_profiles", {})
        if postgres_profile_id in mapping:
            return int(mapping[postgres_profile_id])
    except Exception:
        pass

    from ixbrowser_local_api import IXBrowserClient
    client = IXBrowserClient()
    profiles = client.get_profile_list(keyword=postgres_profile_id, limit=5) or []
    for p in profiles:
        pid = p.get("profile_id") or p.get("id")
        if pid:
            return int(pid)

    raise RuntimeError(
        f"No IXBrowser profile found for '{postgres_profile_id}'. "
        f"Create an IXBrowser profile named '{postgres_profile_id}' "
        f"or add a mapping to E:\\cb-core\\defaults.json under 'ixbrowser_profiles'."
    )


_IX_API = "http://127.0.0.1:53200/api/v2"
_IX_OPEN_TIMEOUT  = 60   # seconds; proxy cold-start can take ~10s
_IX_CLOSE_TIMEOUT = 30


def _ix_post(endpoint: str, params: dict, timeout: int = 30) -> dict:
    """Raw HTTP call to IXBrowser local API (bypasses library's hardcoded 20s timeout)."""
    import requests as _req
    url = f"{_IX_API}/{endpoint}"
    try:
        r = _req.post(url, json=params, timeout=timeout)
        return r.json()
    except Exception as e:
        raise RuntimeError(f"IXBrowser API {endpoint}: {e}")


def ix_open_profile(profile_id: str | int) -> str:
    """Open an IXBrowser profile and return its CDP URL."""
    pid = int(profile_id)
    params = {
        "profile_id": pid,
        "load_extensions": False,
        "load_profile_info_page": False,
        "cookies_backup": False,
        "args": ["--disable-extension-welcome-page", "--no-first-run"],
    }

    for attempt in range(6):
        resp = _ix_post("profile-open", params, timeout=_IX_OPEN_TIMEOUT)
        err = resp.get("error", {})
        code = err.get("code", -1)
        msg  = err.get("message", "")

        if code == 0:
            break

        # Cloud backup in progress — transient; wait and retry
        if "backup" in msg.lower() or "being" in msg.lower():
            wait = 5 * (attempt + 1)
            logger.info(f"IXBrowser cloud sync in progress, retrying in {wait}s...")
            time.sleep(wait)
            continue

        raise RuntimeError(f"IXBrowser open_profile failed (id={pid}): {msg}")
    else:
        raise RuntimeError(f"IXBrowser profile {pid} still syncing after retries.")

    data = resp.get("data", {})
    cdp = (data.get("ws")
           or data.get("cdp_url")
           or data.get("debugging_address"))

    if not cdp:
        raise RuntimeError(f"No CDP URL in IXBrowser response: {data}")

    if not cdp.startswith(("ws://", "http://")):
        cdp = f"ws://{cdp}"

    return cdp


def ix_close_profile(profile_id: str | int) -> None:
    try:
        # cookies_backup=False avoids triggering a cloud sync that blocks reopening
        _ix_post("profile-close",
                 {"profile_id": int(profile_id), "cookies_backup": False},
                 timeout=_IX_CLOSE_TIMEOUT)
    except Exception as e:
        logger.warning(f"IXBrowser close (non-fatal): {e}")


def ix_create_profile(name: str, proxy_id: int | None = None) -> int:
    """Create a new IXBrowser profile and return its profile_id."""
    from ixbrowser_local_api import IXBrowserClient
    client = IXBrowserClient()
    kwargs = {"name": name, "site_url": "https://google.com"}
    if proxy_id:
        kwargs["proxy_id"] = proxy_id
    result = client.create_profile(**kwargs)
    if result is None:
        raise RuntimeError(f"IXBrowser create_profile failed: {client.message}")
    pid = result.get("profile_id") or result.get("id")
    if not pid:
        raise RuntimeError(f"No profile_id in create response: {result}")
    return int(pid)


# ── browser-use agent ─────────────────────────────────────────────────────────────

async def _run_agent(cdp_url: str, task: str, profile: dict,
                     cv_path: str | None = None,
                     task_type: str = "application") -> dict:
    from browser_use import Agent
    from browser_use.browser.session import BrowserSession
    from failure_classifier import classify_failure

    if not OPENROUTER_KEY:
        return {"ok": False, "result": "OPENROUTER_API_KEY not set. Add it to E:\\cb-core\\.env"}

    # Persona block from profile
    persona = _build_persona(profile)

    # CDP session
    browser_session = BrowserSession(cdp_url=cdp_url)

    # Base task prompt (no pre-answers yet)
    task_text = _build_task_prompt(task, persona, task_type)

    # For assessment types: extract page DOM and pre-generate answers via reasoning LLM
    if task_type in ("quiz", "mcq", "assessment", "essay"):
        try:
            from patchright.sync_api import sync_playwright
            with sync_playwright() as pw:
                browser = pw.chromium.connect_over_cdp(cdp_url)
                page = (browser.contexts[0].pages[0]
                        if browser.contexts and browser.contexts[0].pages
                        else None)
                if page:
                    page_text = page.evaluate(
                        "() => (document.body?.innerText || '').slice(0, 5000)"
                    )
                    browser.close()
                    if len(page_text) > 200:
                        pre_answers = await _pregenerate_answers(page_text, task)
                        task_text = _build_task_prompt(task, persona, task_type, pre_answers)
        except Exception as e:
            logger.warning(f"DOM pre-extraction failed (non-fatal): {e}")

    av_files = [cv_path] if cv_path and os.path.exists(cv_path) else []
    profile_email = profile.get("email", "")

    try:
        agent = Agent(
            task=task_text,
            llm=_make_llm(MODEL_WORKHORSE),
            page_extraction_llm=_make_llm(MODEL_VISION),
            judge_llm=_make_llm(MODEL_REASONING),
            use_judge=True,
            browser_session=browser_session,
            available_file_paths=av_files,
            max_failures=5,
        )
    except TypeError:
        # Older browser-use builds without judge_llm
        agent = Agent(
            task=task_text,
            llm=_make_llm(MODEL_WORKHORSE),
            browser_session=browser_session,
            available_file_paths=av_files,
            max_failures=5,
            use_vision=True,
        )

    # Popup handler: LLM judges each new window
    async def _manage_popups():
        try:
            await asyncio.sleep(2)
            page = await browser_session.get_current_page()
            ctx = page.context

            async def _handle_new_page(new_page):
                try:
                    await asyncio.sleep(1.5)
                    url = new_page.url or ""
                    if not url or url in ("about:blank", "chrome://newtab/"):
                        await new_page.close()
                        return
                    try:
                        title = await new_page.title()
                        body  = await new_page.evaluate(
                            "() => (document.body?.innerText || '').slice(0, 400)"
                        )
                    except Exception:
                        title, body = "", ""

                    try:
                        import litellm as ll
                        model = MODEL_REASONING
                        if not model.startswith("openrouter/"):
                            model = f"openrouter/{model}"
                        resp = await ll.acompletion(
                            model=model,
                            api_key=OPENROUTER_KEY,
                            api_base=OPENROUTER_BASE_URL,
                            messages=[{"role": "user", "content": (
                                f"Popup opened during a browser task. CLOSE or KEEP?\n"
                                f"URL: {url[:200]}\nTitle: {title}\nContent: {body[:300]}\n\n"
                                "CLOSE: ads, trackers, cookie banners, spam.\n"
                                "KEEP: OAuth, file upload, payment, captcha, required terms.\n"
                                "Reply with exactly one word: CLOSE or KEEP"
                            )}],
                            max_tokens=5,
                            temperature=0.0,
                        )
                        decision = resp.choices[0].message.content.strip().upper()
                    except Exception:
                        decision = "KEEP"

                    if "CLOSE" in decision:
                        await new_page.close()
                        logger.info(f"Popup [CLOSE]: {url[:80]}")
                    else:
                        logger.info(f"Popup [KEEP]: {url[:80]}")
                except Exception as e:
                    logger.debug(f"Popup handler error: {e}")

            ctx.on("page", _handle_new_page)
        except Exception as e:
            logger.debug(f"Popup handler attach failed: {e}")

    asyncio.ensure_future(_manage_popups())

    # Verify code injector for email OTP
    if profile_email:
        try:
            from verify_code_injector import verify_code_injector
            asyncio.ensure_future(verify_code_injector(browser_session, profile_email))
        except Exception as e:
            logger.debug(f"verify_code_injector unavailable: {e}")

    # Run with deadline
    try:
        result = await asyncio.wait_for(
            agent.run(max_steps=MAX_STEPS),
            timeout=TASK_TIMEOUT,
        )
    except asyncio.TimeoutError:
        return {"ok": False, "result": f"Task exceeded {TASK_TIMEOUT}s timeout"}

    final  = result.final_result() if hasattr(result, "final_result") else str(result)
    errors = [str(e) for e in (result.errors() if hasattr(result, "errors") else []) if e]

    # Use is_successful() which respects the done(success=False) flag — more reliable than
    # text-matching on final_result
    if hasattr(result, "is_successful"):
        ok = result.is_successful() is True
    else:
        is_done = result.is_done() if hasattr(result, "is_done") else True
        ok = is_done and "error" not in (final or "").lower()

    return {"ok": ok, "result": final or (errors[-1] if errors else "completed")}


# ── Dispatch ──────────────────────────────────────────────────────────────────────

def dispatch_job(job_payload: dict) -> dict:
    from failure_classifier import classify_failure

    job_id     = job_payload.get("job_id")
    url        = job_payload.get("url", "")
    profile_id = job_payload.get("profile_id", "")
    company    = job_payload.get("company", "")
    title      = job_payload.get("title", "")

    if not url:
        return {"ok": False, "result": "no URL in payload"}

    if not ix_running():
        return {
            "ok": False,
            "result": (
                f"IXBrowser is not running on {socket.gethostname()}. "
                "Open IXBrowser then retry."
            ),
        }

    # Fetch full job details
    job_raw = _mcp_call("get_job", job_id=job_id)
    if "error" in job_raw:
        return {"ok": False, "result": f"Job fetch failed: {job_raw['error']}"}
    profile_id = profile_id or job_raw.get("profile_id") or ""
    company    = company    or job_raw.get("company", "")
    title      = title      or job_raw.get("title", "")

    if not profile_id:
        return {"ok": False, "result": f"Job {job_id} has no profile_id set."}

    # Fetch candidate profile
    profile_raw = _mcp_call("get_profile", profile_id=profile_id)
    if "error" in profile_raw:
        return {"ok": False, "result": f"Profile fetch failed: {profile_raw['error']}"}

    # Generate tailored CV locally
    cv_pdf_path = None
    cv_result   = _generate_cv(profile_raw, job_raw)
    if cv_result:
        cv_pdf_path = cv_result.get("pdf_path")
        score       = cv_result.get("score", 0)
        logger.info(f"CV score={score}%  pdf={cv_pdf_path}")

    # Resolve IXBrowser profile (creates with correct country proxy if missing)
    profile_location = profile_raw.get("location", "")
    try:
        from proxy_manager import location_to_country, ensure_ixbrowser_profile
        country = location_to_country(profile_location)
        ix_id = ensure_ixbrowser_profile(
            postgres_id=profile_id,
            full_name=profile_raw.get("name", profile_id),
            country=country,
            proxy_type="socks5",
        )
    except Exception:
        # Fallback to defaults.json / name-search
        try:
            ix_id = ix_find_profile(profile_id)
            country = "?"
        except RuntimeError as e:
            return {"ok": False, "result": str(e)}

    logger.info(f"Opening IXBrowser profile {ix_id} for '{profile_id}' (country={country})")

    try:
        cdp_url = ix_open_profile(ix_id)
        logger.info(f"CDP ready: {cdp_url[:70]}")
    except RuntimeError as e:
        return {"ok": False, "result": str(e)}

    # ── MANDATORY: Location verification ─────────────────────────────────────
    import time as _time
    _time.sleep(3)   # let browser fully initialise before IP check
    try:
        from ip_verifier import verify_location, print_location_banner
        ip_result = verify_location(cdp_url, country)
        print_location_banner(ip_result, profile_raw.get("name", profile_id), profile_location)
        if not ip_result["match"]:
            logger.warning(
                f"Location mismatch: expected {country.upper()}, "
                f"got {ip_result['country'].upper()} ({ip_result['ip']}). "
                "Proceeding — may be geo-blocked."
            )
    except Exception as e:
        logger.warning(f"IP verification failed (non-fatal): {e}")
    # ─────────────────────────────────────────────────────────────────────────

    # Build application task
    name     = profile_raw.get("name", "")
    email    = profile_raw.get("email", "")
    phone    = profile_raw.get("phone", "")
    location = profile_raw.get("location", "Remote")
    bio      = (profile_raw.get("bio") or "")[:300]

    base_task = (
        f"Navigate to {url} and complete the job application for this candidate.\n\n"
        f"Candidate:\n"
        f"  Name: {name}\n"
        f"  Email: {email}\n"
        f"  Phone: {phone}\n"
        f"  Location: {location}\n"
    )
    if bio:
        base_task += f"\nBackground: {bio}\n"
    if cv_pdf_path and os.path.exists(cv_pdf_path):
        base_task += (
            f"\nA tailored CV is available at {cv_pdf_path} -- "
            "upload it when the form requests a CV or resume file.\n"
        )
    base_task += (
        "\nInstructions:\n"
        "- Fill every required field.\n"
        "- For free-text fields (cover letter, summary), write from the candidate's perspective.\n"
        "- If asked for years of experience, use 2-4 years as a default.\n"
        "- Submit the application when complete.\n"
        "- If you cannot proceed (login wall, site error, already applied), "
        "describe exactly what happened.\n"
    )

    # Run agent
    try:
        result = asyncio.run(_run_agent(
            cdp_url, base_task, profile_raw, cv_pdf_path,
            task_type=job_raw.get("task_type", "application"),
        ))
    except Exception as e:
        failure = classify_failure(str(e))
        result = {"ok": False, "result": str(e), "failure_type": failure}
    finally:
        ix_close_profile(ix_id)

    return result


# ── Main loop ─────────────────────────────────────────────────────────────────────

def list_ix_profiles():
    hostname = socket.gethostname()
    if not ix_running():
        print(f"[{hostname}] IXBrowser not running - open IXBrowser and try again.")
        return
    profiles = ix_list_profiles()
    if not profiles:
        print("No IXBrowser profiles found.")
        return
    print(f"[{hostname}] {len(profiles)} IXBrowser profile(s):")
    for p in profiles:
        pid  = p.get("profile_id") or p.get("id", "?")
        name = p.get("name", "?")
        print(f"  IXBrowser profile_id={pid!r}  name={name!r}")
    print(
        "\nMap to postgres profile IDs in E:\\cb-core\\defaults.json:\n"
        '  { "ixbrowser_profiles": { "james-okafor": "<ix-profile-id>" } }'
    )


def process_queue(once: bool = False):
    from failure_classifier import classify_failure

    hostname = socket.gethostname()
    print(f"Queue bridge [{hostname}] - polling {APPROVED_KEY} every {POLL_INTERVAL}s")

    while True:
        payload_str = _lpop(APPROVED_KEY)
        if payload_str:
            try:
                payload = json.loads(payload_str)
            except Exception:
                payload = {"raw": payload_str}

            job_id = payload.get("job_id", "?")
            print(f"\n[job {job_id}] {payload.get('url', '?')[:80]}")

            _mcp_call("update_job_status", job_id=job_id, status="applying")
            result = dispatch_job(payload)
            ok     = result["ok"]
            res    = result["result"]
            print(f"[job {job_id}] ok={ok}")
            if not ok:
                print(f"[job {job_id}] error: {str(res)[:300]}", flush=True)

            # Classify failure for accurate postgres status
            failure_type = result.get("failure_type") or (
                classify_failure(str(res)) if not ok else "none"
            )

            if ok:
                status = "applied"
            elif failure_type == "captcha":
                status = "failed"  # CAPTCHA solver exhausted
            elif failure_type == "session_expired":
                status = "failed"
            elif isinstance(res, str) and "assessment" in res.lower():
                status = "assessment_needed"
            else:
                status = "failed"

            result_str = json.dumps(res) if isinstance(res, dict) else str(res)
            _mcp_call("update_job_status", job_id=job_id, status=status, result=result_str[:4000])
            _rpush(RESULTS_KEY, json.dumps({
                "job_id": job_id, "ok": ok,
                "status": status,
                "failure_type": failure_type,
                "result": result_str[:1000],
            }))
            print(f"[job {job_id}] status: {status} ({failure_type})")

        elif once:
            print("Queue empty.")
            break
        else:
            time.sleep(POLL_INTERVAL)


def main():
    parser = argparse.ArgumentParser(description="CareerBridge desktop application dispatcher")
    parser.add_argument("--once", action="store_true", help="Process queue then exit")
    parser.add_argument("--list-profiles", action="store_true",
                        help="List IXBrowser profiles and exit")
    args = parser.parse_args()

    if args.list_profiles:
        list_ix_profiles()
    else:
        process_queue(once=args.once)


if __name__ == "__main__":
    main()
