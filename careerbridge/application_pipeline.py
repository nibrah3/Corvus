"""
application_pipeline.py — Application form-filling pipeline.

Single responsibility: drive one job application from page open to submission.

Architecture:
  Agent       → browser-use (autonomous loop; no manual element targeting)
  LLM stack   → Haiku workhorse + gpt-4o-mini vision/judge (3-model)
  Execution   → browser-use native CDP (speed-focused, no behavioral humanization)
  Pre-answers → DOM text extracted once per page → one reasoning LLM call → answers
                injected into agent task before the loop starts (reduces agent steps)

Concurrency:
  ConcurrentApplicationRunner — asyncio.Queue + N worker coroutines.
  Call run_batch([cfg, ...]) to process many jobs in parallel.

No humanization: application throughput is the priority.
For stealth/behavioral humanization see assessment_pipeline.py.

Usage (single job):
    from careerbridge.application_pipeline import ApplicationPipeline, ApplicationConfig
    cfg = ApplicationConfig(cdp_url="ws://...", url="https://...", profile={...})
    result = await ApplicationPipeline(cfg).run()

Usage (batch / concurrent):
    runner = ConcurrentApplicationRunner(workers=3)
    results = await runner.run_batch([cfg1, cfg2, cfg3])
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
import sys
import time
from dataclasses import dataclass, field
from typing import Any, Optional

CB_DIR = os.path.normpath(os.path.join(os.path.dirname(__file__), ".."))
if CB_DIR not in sys.path:
    sys.path.insert(0, CB_DIR)

log = logging.getLogger(__name__)

_OPENROUTER_KEY     = os.environ.get("OPENROUTER_API_KEY", "")
_OPENROUTER_BASE    = os.environ.get("OPENROUTER_BASE_URL", "https://openrouter.ai/api/v1")
# BROWSER_USE_MODEL: model for the browser-use autonomous agent. Must NOT route through
# Amazon Bedrock (Bedrock rejects integer 'minimum' in JSON schema). Defaults to gpt-4o-mini
# which goes through OpenAI's API and has full structured-output support.
_MODEL_WORKHORSE    = os.environ.get("BROWSER_USE_MODEL",           "openai/gpt-4o-mini")
_MODEL_VISION       = os.environ.get("OPENROUTER_MODEL_VISION",     "openai/gpt-4o-mini")
_MODEL_REASONING    = os.environ.get("OPENROUTER_MODEL_REASONING",  "openai/gpt-4o-mini")

_TAB_CONSTRAINT = (
    "CRITICAL BROWSER RULES:\n"
    "- Stay on the task page. Follow site-driven redirects and new tabs.\n"
    "- Do NOT open new tabs to search for answers or visit external sites.\n"
    "- Click a field first, then type into it.\n"
)

_PRE_ANSWER_SYSTEM = (
    "You are pre-reasoning answers for an online form so a browser agent can fill it quickly. "
    "Identify every question, required field, or interactive element on the page. "
    "For each one, provide the best answer for this candidate. "
    "Return a numbered list — one answer per line. No explanations, no markdown."
)

_PRE_ANSWER_PERSONA_SUFFIX = (
    "\n\nFor any free-text / prose answers, write in this specific person's natural voice "
    "exactly as described below. Factual content must remain accurate; only style changes.\n"
)


# ── Config ────────────────────────────────────────────────────────────────────

@dataclass
class ApplicationConfig:
    cdp_url:     str            # ws:// CDP endpoint (from IXBrowser or psutil scan)
    url:         str            # job application URL to navigate to
    profile:     dict           # candidate profile dict from Postgres
    cv_path:     Optional[str] = None   # absolute path to tailored CV PDF
    task_type:   str           = "application"  # application | assessment | mcq | essay
    max_steps:   int           = 50
    timeout_s:   int           = 3600
    job_id:      Optional[Any] = None   # for logging / result tracking


# ── Result ────────────────────────────────────────────────────────────────────

@dataclass
class ApplicationResult:
    ok:           bool
    job_id:       Optional[Any] = None
    status:       str           = "unknown"   # applied | failed | assessment_needed
    failure_type: str           = "none"
    llm_calls:    int           = 0
    steps_taken:  int           = 0
    summary:      str           = ""
    error:        Optional[str] = None


# ── LLM helpers ───────────────────────────────────────────────────────────────

def _make_llm(model: str):
    from browser_use.llm.litellm.chat import ChatLiteLLM
    if not model.startswith("openrouter/"):
        model = f"openrouter/{model}"
    return ChatLiteLLM(
        model=model,
        api_key=_OPENROUTER_KEY,
        api_base=_OPENROUTER_BASE,
        temperature=0.0,
    )


async def _pregenerate_answers(page_text: str, candidate_block: str,
                               persona_prompt: str = "") -> str:
    """One reasoning-LLM call → numbered answer list. Returns '' on failure."""
    if not page_text.strip():
        return ""
    try:
        import litellm as ll
        model = _MODEL_REASONING
        if not model.startswith("openrouter/"):
            model = f"openrouter/{model}"
        sys_prompt = _PRE_ANSWER_SYSTEM
        if persona_prompt:
            sys_prompt = sys_prompt + _PRE_ANSWER_PERSONA_SUFFIX + persona_prompt[:700]
        resp = await ll.acompletion(
            model=model,
            api_key=_OPENROUTER_KEY,
            api_base=_OPENROUTER_BASE,
            messages=[
                {"role": "system", "content": sys_prompt},
                {"role": "user", "content": (
                    f"Candidate info:\n{candidate_block}\n\n"
                    f"Page content:\n{page_text[:4000]}"
                )},
            ],
            max_tokens=900,
            temperature=0.0,
        )
        answers = (resp.choices[0].message.content or "").strip()
        # Strip preamble if model ignores system prompt
        lower = answers.lower()
        for pre in ("here are the answers", "sure,", "of course,", "the answers are"):
            if lower.startswith(pre):
                idx = answers.find("1.")
                if idx > 0:
                    answers = answers[idx:].strip()
                break
        log.debug("Pre-answers: %d chars", len(answers))
        return answers
    except Exception as e:
        log.warning("Pre-answer LLM failed (non-fatal): %s", e)
        return ""


# ── Persona / task construction ───────────────────────────────────────────────

def _build_candidate_block(profile: dict) -> str:
    parts = []
    if name := profile.get("name"):
        parts.append(f"Name: {name}")
    if email := profile.get("email"):
        parts.append(f"Email: {email}")
    if phone := profile.get("phone"):
        parts.append(f"Phone: {phone}")
    if loc := profile.get("location"):
        parts.append(f"Location: {loc}")
    if bio := (profile.get("bio") or "")[:400]:
        parts.append(f"Background: {bio}")

    skills = profile.get("skills") or "[]"
    try:
        skill_list = json.loads(skills) if isinstance(skills, str) else skills
        if skill_list:
            parts.append("Skills: " + ", ".join(skill_list[:20]))
    except Exception:
        pass

    exp = profile.get("experience") or "[]"
    try:
        exp_list = json.loads(exp) if isinstance(exp, str) else exp
        lines = []
        for e in (exp_list or [])[:4]:
            if isinstance(e, dict):
                lines.append(
                    f"  - {e.get('role','')} at {e.get('company','')} "
                    f"({e.get('years', e.get('duration', ''))})"
                )
        if lines:
            parts.append("Experience:\n" + "\n".join(lines))
    except Exception:
        pass

    return "\n".join(parts)


def _build_task_prompt(
    url: str,
    profile: dict,
    cv_path: Optional[str],
    task_type: str,
    pre_answers: str = "",
    persona_prompt: str = "",
) -> str:
    candidate = _build_candidate_block(profile)

    if persona_prompt:
        persona_prefix = (
            f"You are completing this task as the following candidate:\n{candidate}\n\n"
            "Write all prose/text EXACTLY in this person's natural voice. "
            "Their specific writing style:\n"
            f"{persona_prompt[:600]}\n\n"
        )
    else:
        persona_prefix = (
            f"You are completing this task as the following candidate:\n{candidate}\n\n"
            "Write all prose/text in that candidate's natural voice and perspective.\n\n"
        )

    if task_type in ("assessment", "quiz", "mcq", "essay"):
        reasoning_note = (
            "For each question: read carefully, think through which answer fits the "
            "candidate's profile best, then select it.\n\n"
        )
    else:
        reasoning_note = ""

    base = (
        f"Navigate to {url} and complete the job application.\n\n"
        "Instructions:\n"
        "- Fill every required field.\n"
        "- For free-text fields, write from the candidate's perspective.\n"
        "- Default years of experience: 2–4 years unless profile says otherwise.\n"
        "- Submit when complete.\n"
        "- If blocked (login wall, site error, already applied), describe what happened.\n"
    )

    if cv_path and os.path.exists(cv_path):
        base += f"\nA tailored CV is available at {cv_path} — upload it when asked.\n"

    prompt = f"{_TAB_CONSTRAINT}\n{persona_prefix}{reasoning_note}{base}"

    if pre_answers:
        prompt += (
            "\n\n=== PRE-REASONED ANSWERS (use these exactly) ===\n"
            f"{pre_answers}\n"
            "Navigate to each field and enter the corresponding answer."
        )

    return prompt


# ── DOM text extraction via CDP (patchright) ──────────────────────────────────

async def _extract_page_text(cdp_url: str) -> str:
    try:
        from patchright.async_api import async_playwright
        async with async_playwright() as pw:
            browser = await pw.chromium.connect_over_cdp(cdp_url)
            ctx = browser.contexts[0] if browser.contexts else None
            page = ctx.pages[0] if (ctx and ctx.pages) else None
            if page is None:
                return ""
            text = await page.evaluate(
                "(function(){ return (document.body?.innerText || '').slice(0, 5000); })()"
            )
            await browser.close()
            return text or ""
    except Exception as e:
        log.debug("DOM text extraction failed: %s", e)
        return ""


# ── Failure classification (inline — no external dependency) ──────────────────

def _classify_failure(msg: str) -> str:
    m = (msg or "").lower()
    if any(k in m for k in ("captcha", "recaptcha", "hcaptcha", "turnstile")):
        return "captcha"
    if any(k in m for k in ("login", "sign in", "authenticate", "session expired")):
        return "session_expired"
    if "already applied" in m or "duplicate" in m:
        return "duplicate"
    if any(k in m for k in ("timeout", "timed out")):
        return "timeout"
    if any(k in m for k in ("assessment", "test", "quiz", "evaluation")):
        return "assessment_needed"
    if any(k in m for k in ("not found", "404", "page unavailable")):
        return "not_found"
    return "unknown"


# ── Popup handler ─────────────────────────────────────────────────────────────

async def _attach_popup_handler(browser_session) -> None:
    """Attach an LLM judge to auto-close spam popups on new pages."""
    await asyncio.sleep(2)
    try:
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
                        "(function(){ return (document.body?.innerText||'').slice(0,300); })()"
                    )
                except Exception:
                    title, body = "", ""

                try:
                    import litellm as ll
                    model = _MODEL_REASONING
                    if not model.startswith("openrouter/"):
                        model = f"openrouter/{model}"
                    resp = await ll.acompletion(
                        model=model,
                        api_key=_OPENROUTER_KEY,
                        api_base=_OPENROUTER_BASE,
                        messages=[{"role": "user", "content": (
                            f"Popup during browser task. CLOSE or KEEP?\n"
                            f"URL: {url[:200]}\nTitle: {title}\nBody: {body}\n"
                            "CLOSE: ads, cookie banners, spam.\n"
                            "KEEP: OAuth, upload, payment, captcha, required terms.\n"
                            "Reply with exactly one word: CLOSE or KEEP"
                        )}],
                        max_tokens=5,
                        temperature=0.0,
                    )
                    decision = (resp.choices[0].message.content or "").strip().upper()
                except Exception:
                    decision = "KEEP"

                if "CLOSE" in decision:
                    await new_page.close()
                    log.info("Popup closed: %s", url[:80])
                else:
                    log.info("Popup kept: %s", url[:80])
            except Exception as e:
                log.debug("Popup handler error: %s", e)

        ctx.on("page", _handle_new_page)
    except Exception as e:
        log.debug("Popup handler attach failed: %s", e)


# ── ApplicationPipeline ───────────────────────────────────────────────────────

class ApplicationPipeline:
    """
    Drive one job application session using browser-use as the autonomous agent.

    Speed-focused: no mouse humanization, no FSM, no accessibility tree reasoning.
    For assessment/behavioral pipeline see assessment_pipeline.py.
    """

    def __init__(self, config: ApplicationConfig) -> None:
        self._cfg = config
        self._result = ApplicationResult(ok=False, job_id=config.job_id)

    async def run(self) -> ApplicationResult:
        if not _OPENROUTER_KEY:
            self._result.error = "OPENROUTER_API_KEY not set"
            self._result.status = "failed"
            self._result.failure_type = "config_error"
            return self._result

        try:
            await self._execute()
        except Exception as e:
            self._result.error = str(e)
            self._result.status = "failed"
            self._result.failure_type = _classify_failure(str(e))
            log.error("Application pipeline error (job=%s): %s", self._cfg.job_id, e)

        return self._result

    async def _execute(self) -> None:
        from browser_use import Agent
        from browser_use.browser.session import BrowserSession

        cfg = self._cfg

        # 0. Load persona for this profile (auto-generates if missing)
        profile_id = cfg.profile.get("profile_id") or cfg.profile.get("id") or ""
        persona_prompt = ""
        if profile_id:
            try:
                from answer_mcp._persona import get_persona_prompt, generate_persona
                persona_prompt = get_persona_prompt(profile_id) or ""
                if not persona_prompt:
                    log.info("Auto-generating persona for profile %r", profile_id)
                    persona_prompt = generate_persona(profile_id, {})["persona_prompt"]
            except Exception as e:
                log.debug("Persona load failed (non-fatal): %s", e)

        # 1. Pre-answer generation: extract DOM text → one LLM call
        page_text = ""
        pre_answers = ""
        if cfg.task_type in ("assessment", "quiz", "mcq", "essay"):
            page_text = await _extract_page_text(cfg.cdp_url)
            if len(page_text) > 200:
                candidate_block = _build_candidate_block(cfg.profile)
                pre_answers = await _pregenerate_answers(
                    page_text, candidate_block, persona_prompt=persona_prompt
                )
                if pre_answers:
                    self._result.llm_calls += 1

        # 2. Build task prompt
        task_text = _build_task_prompt(
            cfg.url, cfg.profile, cfg.cv_path, cfg.task_type, pre_answers,
            persona_prompt=persona_prompt,
        )

        # 3. CDP session
        browser_session = BrowserSession(cdp_url=cfg.cdp_url)

        # 4. Build agent (try newer API first, fall back for older browser-use builds)
        try:
            agent = Agent(
                task=task_text,
                llm=_make_llm(_MODEL_WORKHORSE),
                page_extraction_llm=_make_llm(_MODEL_VISION),
                judge_llm=_make_llm(_MODEL_REASONING),
                use_judge=True,
                use_vision=False,
                browser_session=browser_session,
                available_file_paths=[cfg.cv_path] if cfg.cv_path and os.path.exists(cfg.cv_path) else [],
                max_failures=5,
            )
        except TypeError:
            agent = Agent(
                task=task_text,
                llm=_make_llm(_MODEL_WORKHORSE),
                browser_session=browser_session,
                available_file_paths=[cfg.cv_path] if cfg.cv_path and os.path.exists(cfg.cv_path) else [],
                max_failures=5,
                use_vision=False,
            )

        # 5. Popup handler + verify-code injector (both fire-and-forget)
        asyncio.ensure_future(_attach_popup_handler(browser_session))

        profile_email = cfg.profile.get("email", "")
        if profile_email:
            try:
                from verify_code_injector import verify_code_injector
                asyncio.ensure_future(verify_code_injector(browser_session, profile_email))
            except Exception:
                pass

        # 6. Run with deadline
        try:
            result = await asyncio.wait_for(
                agent.run(max_steps=cfg.max_steps),
                timeout=cfg.timeout_s,
            )
        except asyncio.TimeoutError:
            self._result.error = f"Timed out after {cfg.timeout_s}s"
            self._result.status = "failed"
            self._result.failure_type = "timeout"
            return

        # 7. Interpret result
        final  = result.final_result() if hasattr(result, "final_result") else str(result)
        errors = [str(e) for e in (result.errors() if hasattr(result, "errors") else []) if e]
        steps  = result.number_of_steps() if hasattr(result, "number_of_steps") else 0

        if hasattr(result, "is_successful"):
            ok = result.is_successful() is True
        else:
            is_done = result.is_done() if hasattr(result, "is_done") else True
            ok = is_done and "error" not in (final or "").lower()

        # Estimate LLM calls from steps (workhorse: 1 per step, vision sporadic)
        self._result.llm_calls += max(steps, 1)
        self._result.steps_taken = steps
        self._result.ok = ok
        self._result.summary = (final or (errors[-1] if errors else "completed"))[:2000]

        failure_type = _classify_failure(self._result.summary if not ok else "")
        self._result.failure_type = failure_type

        if ok:
            self._result.status = "applied"
        elif failure_type == "assessment_needed":
            self._result.status = "assessment_needed"
        else:
            self._result.status = "failed"


# ── ConcurrentApplicationRunner ───────────────────────────────────────────────

class ConcurrentApplicationRunner:
    """
    Asyncio worker pool for concurrent application processing.

    Creates N worker coroutines that pull from an asyncio.Queue.
    Each worker runs one ApplicationPipeline at a time.

    Usage:
        runner = ConcurrentApplicationRunner(workers=3)
        results = await runner.run_batch([cfg1, cfg2, cfg3, cfg4, cfg5])
    """

    def __init__(self, workers: int = 3) -> None:
        self._workers = max(1, workers)

    async def run_batch(self, configs: list[ApplicationConfig]) -> list[ApplicationResult]:
        if not configs:
            return []

        queue: asyncio.Queue[ApplicationConfig | None] = asyncio.Queue()
        results: list[ApplicationResult] = []
        lock = asyncio.Lock()

        for cfg in configs:
            await queue.put(cfg)
        # Sentinel values to shut down workers
        for _ in range(self._workers):
            await queue.put(None)

        async def worker(worker_id: int) -> None:
            while True:
                cfg = await queue.get()
                if cfg is None:
                    queue.task_done()
                    return
                log.info("Worker %d: starting job=%s", worker_id, cfg.job_id)
                try:
                    result = await ApplicationPipeline(cfg).run()
                except Exception as e:
                    result = ApplicationResult(
                        ok=False, job_id=cfg.job_id,
                        status="failed", failure_type="unknown",
                        error=str(e),
                    )
                async with lock:
                    results.append(result)
                log.info(
                    "Worker %d: job=%s → %s (%s)",
                    worker_id, cfg.job_id, result.status, result.failure_type,
                )
                queue.task_done()

        workers = [asyncio.create_task(worker(i)) for i in range(self._workers)]
        await queue.join()
        await asyncio.gather(*workers, return_exceptions=True)
        return results
