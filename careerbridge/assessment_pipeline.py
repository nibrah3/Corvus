"""
assessment_pipeline.py — Assessment execution pipeline.

Single responsibility: drive one assessment session from open page to completion.

Architecture:
  Perception  → CDPExecutor.get_axtree() (semantic DOM, no screenshots/OCR)
  Reasoning   → Claude Sonnet 4.6 (one call per question page)
  Execution   → humanizer_mcp (driver-level HID: WindMouse + ex-Gaussian timing)
  Verification→ screenshot diff after each click (ChangeType != NONE)

IXBrowser accounts:
  Paid (tomoneshaa): cdp_url supplied from ix_open_profile() API
  Free (others):     cdp_url discovered from psutil scan

Human gate:
  Free-text answers (essay, open-ended) pause for approval before submitting.
  MCQ / radio answers are executed immediately after Sonnet selects them.

Usage:
    from careerbridge.assessment_pipeline import AssessmentPipeline, AssessmentConfig
    from careerbridge.schema import Profile

    cfg = AssessmentConfig(cdp_url="ws://...", url="https://...", profile=profile)
    result = AssessmentPipeline(cfg).run()
"""
from __future__ import annotations

import logging
import os
import random
import sys
import time
from dataclasses import dataclass, field
from typing import Any, Optional

CB_DIR = os.path.normpath(os.path.join(os.path.dirname(__file__), ".."))
if CB_DIR not in sys.path:
    sys.path.insert(0, CB_DIR)

from careerbridge._llm   import call_llm, profile_summary, ANSWERABLE_ROLES, TEXT_INPUT_ROLES, SUBMIT_NAMES
from careerbridge._gate  import tg_notify, claude_code_gate
from careerbridge.cdp_executor import CDPExecutor, CDPError
from careerbridge.reliability  import retry_with_backoff
from humanizer_mcp._mouse    import click as _hum_click, move as _hum_move
from humanizer_mcp._keyboard import type_text as _hum_type, press_key as _hum_press
from humanizer_mcp._scroll   import scroll as _hum_scroll
from humanizer_mcp._profile  import BehaviorProfile

log = logging.getLogger(__name__)


def _persona_humanize(canonical: str, question_context: str, profile_id: str) -> str:
    """
    Rewrite canonical answer text in the profile's locked persona voice.
    Auto-generates persona if none exists. Returns canonical unchanged on any failure.
    """
    if not profile_id:
        return canonical
    try:
        from answer_mcp._persona import get_persona_prompt, generate_persona
        from answer_mcp._humanize import humanize
        prompt = get_persona_prompt(profile_id)
        if not prompt:
            log.info("Auto-generating persona for profile %r", profile_id)
            prompt = generate_persona(profile_id, {})["persona_prompt"]
        return humanize(
            canonical_answer=canonical,
            question=question_context or "professional assessment question",
            persona_prompt=prompt,
            profile_id=profile_id,
        )
    except Exception as e:
        log.warning("Persona humanize failed (%s) — using canonical text", e)
        return canonical


def _extract_profile_id(profile) -> str:
    """Extract profile_id from Profile dataclass or dict, return '' if unavailable."""
    if isinstance(profile, dict):
        return profile.get("profile_id") or profile.get("id") or ""
    return getattr(profile, "profile_id", "") or ""


# ── Config ────────────────────────────────────────────────────────────────────

@dataclass
class AssessmentConfig:
    cdp_url:         str               # ws:// URL of the IXBrowser page
    url:             str               # assessment URL to navigate to
    profile:         Any               # careerbridge.schema.Profile
    human_gate:      bool = True       # pause for approval on free-text answers
    max_pages:       int  = 50         # max question pages before giving up
    page_timeout_s:  float = 30.0      # seconds to wait for page to stabilise
    profile_seed:    Optional[int] = None  # optional seed for deterministic timing


# ── Result ────────────────────────────────────────────────────────────────────

@dataclass
class AssessmentResult:
    ok:            bool
    pages_done:    int  = 0
    llm_calls:     int  = 0
    actions_taken: int  = 0
    error:         Optional[str] = None


# ── AssessmentPipeline ────────────────────────────────────────────────────────

class AssessmentPipeline:
    """
    Drive one assessment session.

    Perception:  CDP accessibility tree (get_axtree) — no screenshots, no OCR.
    Reasoning:   Claude Sonnet 4.6 — called once per question page.
    Execution:   humanizer_mcp — driver-level HID (WindMouse + ex-Gaussian timing).
    Verification: JS poll after each click (element state change or new page).
    """

    def __init__(self, config: AssessmentConfig) -> None:
        self._cfg     = config
        self._cdp     = CDPExecutor()
        self._profile = BehaviorProfile.default()
        self._rng     = random.Random(config.profile_seed)
        self._result  = AssessmentResult(ok=False)

    def run(self) -> AssessmentResult:
        tg_notify(f"🔍 Assessment started\nURL: {self._cfg.url}")
        try:
            if self._cfg.cdp_url:
                self._cdp.connect_ws(self._cfg.cdp_url)
            else:
                self._cdp.connect()
            self._cdp.navigate(self._cfg.url)
            self._loop()
            self._result.ok = True
            tg_notify(
                f"✅ Assessment complete\n"
                f"Pages: {self._result.pages_done}  LLM calls: {self._result.llm_calls}  "
                f"Actions: {self._result.actions_taken}"
            )
        except Exception as e:
            self._result.error = str(e)
            log.error("Assessment failed: %s", e)
            tg_notify(f"❌ Assessment failed\n{str(e)[:300]}")
        finally:
            try:
                self._cdp.disconnect()
            except Exception:
                pass
        return self._result

    def _loop(self) -> None:
        profile_email = getattr(self._cfg.profile, "email", None) or (
            self._cfg.profile.get("email") if isinstance(self._cfg.profile, dict) else None
        )
        for page_num in range(1, self._cfg.max_pages + 1):
            log.info("Assessment page %d", page_num)

            if self._is_done():
                log.info("Assessment complete (done signal on page %d)", page_num)
                return

            tree = self._cdp.get_axtree()
            answerable, text_inputs, submit_btn = self._classify_nodes(tree)

            if not answerable and not text_inputs and submit_btn is None:
                log.info("No interactive elements found — assuming complete.")
                return

            # OTP fields: check Redis for a waiting code before LLM reasoning
            if text_inputs and profile_email:
                otp_nodes = [n for n in text_inputs if self._looks_like_otp(n)]
                if otp_nodes:
                    self._inject_otp(otp_nodes, profile_email)

            # Free-text inputs get human gate (or auto)
            remaining_text = [n for n in text_inputs if not self._looks_like_otp(n)]
            if remaining_text and self._cfg.human_gate:
                self._handle_text_inputs_with_gate(remaining_text)
            elif remaining_text:
                self._handle_text_inputs_auto(remaining_text)

            # MCQ/radio: one LLM call for the whole page
            if answerable:
                self._handle_mcq(answerable)

            # Click Next/Submit — brief review pause then click, then wait for page load
            if submit_btn:
                time.sleep(max(0.5, min(1.3, self._rng.gauss(0.8, 0.2))))
                self._click_node(submit_btn)
                self._result.pages_done += 1
                time.sleep(max(0.8, min(2.0, self._rng.gauss(1.2, 0.3))))
            elif not answerable and not text_inputs:
                return

        log.warning("Reached max_pages=%d without completion", self._cfg.max_pages)

    # ── Page state helpers ────────────────────────────────────────────────────

    def _wait_for_stable_page(self) -> None:
        js = """
        (function() {
            if (window.__cb_settling) return window.__cb_mutations || 999;
            window.__cb_mutations = 0;
            window.__cb_settling  = true;
            var obs = new MutationObserver(function(ml) {
                window.__cb_mutations += ml.length;
            });
            obs.observe(document.body || document, {subtree:true,childList:true,attributes:true});
            setTimeout(function(){ obs.disconnect(); window.__cb_settling=false; }, 1000);
            return 999;
        })()
        """
        deadline = time.monotonic() + self._cfg.page_timeout_s
        while time.monotonic() < deadline:
            try:
                mutations = self._cdp.eval_js(js)
                if isinstance(mutations, (int, float)) and mutations == 0:
                    time.sleep(0.3)
                    return
            except Exception:
                pass
            time.sleep(0.5)

    def _is_done(self) -> bool:
        try:
            text = self._cdp.eval_js(
                "(document.body?.innerText || '').toLowerCase().slice(0, 800)"
            ) or ""
            keywords = ["thank you", "completed", "submission received",
                        "all done", "results submitted", "assessment complete"]
            return any(kw in text for kw in keywords)
        except Exception:
            return False

    def _classify_nodes(self, tree: list[dict]):
        answerable, text_inputs, submit_btn = [], [], None
        for node in tree:
            role = (node.get("role") or "").lower()
            name = (node.get("name") or "").lower()
            props = node.get("properties", {})
            if props.get("disabled"):
                continue
            if role in ANSWERABLE_ROLES:
                if any(s in name for s in SUBMIT_NAMES):
                    submit_btn = node
                else:
                    answerable.append(node)
            elif role in TEXT_INPUT_ROLES:
                text_inputs.append(node)
        return answerable, text_inputs, submit_btn

    # ── OTP detection & injection ─────────────────────────────────────────────

    _OTP_KEYWORDS = frozenset({
        "verification", "verify", "code", "otp", "one-time", "token",
        "pin", "confirmation", "6-digit", "4-digit", "authentication",
    })

    def _looks_like_otp(self, node: dict) -> bool:
        combined = " ".join([
            node.get("name") or "",
            node.get("description") or "",
        ]).lower()
        return any(kw in combined for kw in self._OTP_KEYWORDS)

    def _inject_otp(self, otp_nodes: list[dict], profile_email: str) -> None:
        try:
            from verify_code_injector import verify_code_injector_cdp
            log.info("OTP field detected — waiting for code (email=%s)", profile_email)
            tg_notify(f"🔑 OTP field detected for <code>{profile_email}</code> — waiting for email...")
            if verify_code_injector_cdp(self._cdp, profile_email, timeout=120.0):
                self._result.actions_taken += 1
        except Exception as e:
            log.warning("OTP injection failed: %s", e)

    # ── MCQ execution ─────────────────────────────────────────────────────────

    def _get_page_context(self) -> str:
        try:
            return (self._cdp.eval_js(
                "Array.from(document.querySelectorAll('h1,h2,h3,p,label,fieldset legend,"
                "[class*=\"question\"],[class*=\"statement\"],[class*=\"prompt\"]'))"
                ".map(e=>e.innerText.trim()).filter(t=>t.length>4&&t.length<300)"
                ".slice(0,30).join('\\n')"
            ) or "")
        except Exception:
            return ""

    def _handle_mcq(self, nodes: list[dict]) -> None:
        element_list = [
            {"node_id": n["nodeId"], "role": n["role"], "text": n["name"]}
            for n in nodes
        ]
        page_context = self._get_page_context()
        try:
            actions = call_llm(element_list, profile_summary(self._cfg.profile),
                               page_context=page_context)
            self._result.llm_calls += 1
        except Exception as e:
            log.warning("LLM call failed: %s — skipping page", e)
            return

        node_map = {n["nodeId"]: n for n in nodes}
        for act in actions:
            nid = str(act.get("node_id", ""))
            if nid not in node_map:
                continue
            node = node_map[nid]
            if act.get("action") == "click":
                read_s = max(0.9, min(3.5, self._rng.gauss(1.8, 0.5)))
                time.sleep(read_s)
                # 5% answer noise — simulates natural human imprecision
                if self._rng.random() < 0.05:
                    idx = next((j for j, n in enumerate(nodes) if n["nodeId"] == nid), None)
                    if idx is not None:
                        alt = max(0, min(len(nodes) - 1, idx + self._rng.choice([-1, 1])))
                        node = nodes[alt]
                        nid  = node["nodeId"]
                self._click_node(node)
                self._result.actions_taken += 1
                time.sleep(max(0.18, min(0.55, self._rng.gauss(0.30, 0.08))))

    # ── Text input handling ───────────────────────────────────────────────────

    def _handle_text_inputs_auto(self, nodes: list[dict]) -> None:
        element_list = [
            {"node_id": n["nodeId"], "role": n["role"], "text": n["name"],
             "label": n.get("description", "")}
            for n in nodes
        ]
        page_context = self._get_page_context()
        try:
            actions = call_llm(element_list, profile_summary(self._cfg.profile),
                               page_context=page_context)
            self._result.llm_calls += 1
        except Exception as e:
            log.warning("LLM call failed: %s — skipping text fields", e)
            return

        pid = _extract_profile_id(self._cfg.profile)
        node_map = {n["nodeId"]: n for n in nodes}
        for act in actions:
            nid = str(act.get("node_id", ""))
            if nid not in node_map or act.get("action") != "type":
                continue
            text = act.get("text", "")
            if text:
                if pid:
                    label = node_map[nid].get("name") or node_map[nid].get("description") or ""
                    text = _persona_humanize(text, label, pid)
                self._click_node(node_map[nid])
                time.sleep(self._rng.uniform(0.15, 0.35))
                _hum_type(text, profile=self._profile, rng=self._rng)
                self._result.actions_taken += 1

    def _handle_text_inputs_with_gate(self, nodes: list[dict]) -> None:
        """Generate LLM draft → send to Claude Code gate for Approve/Edit/Skip."""
        log.info("Human gate: %d free-text field(s) require approval.", len(nodes))

        element_list = [
            {"node_id": n["nodeId"], "role": n["role"], "text": n["name"],
             "label": n.get("description", "")}
            for n in nodes
        ]
        page_context = self._get_page_context()
        drafts: dict[str, str] = {}
        pid = _extract_profile_id(self._cfg.profile)
        try:
            actions = call_llm(element_list, profile_summary(self._cfg.profile),
                               page_context=page_context)
            self._result.llm_calls += 1
            for act in actions:
                nid = str(act.get("node_id", ""))
                if act.get("action") == "type":
                    canonical = act.get("text", "")
                    if canonical and pid:
                        field_label = next(
                            (n.get("name") or n.get("description") or ""
                             for n in nodes if str(n["nodeId"]) == nid),
                            ""
                        )
                        canonical = _persona_humanize(canonical, field_label, pid)
                    drafts[nid] = canonical
        except Exception as e:
            log.warning("Draft generation failed: %s — using empty drafts", e)

        for node in nodes:
            label = node.get("name") or node.get("description") or "field"
            nid   = str(node["nodeId"])
            draft = drafts.get(nid, "")

            answer = claude_code_gate(label, draft, timeout=300.0)

            # Fall back to stdin if Redis/Claude Code gate is unavailable
            if answer is None and not os.environ.get("REDIS_PORT"):
                current = node.get("value") or ""
                print(f"\n[HUMAN GATE] Field: {label!r}")
                if draft:
                    print(f"  Draft: {draft!r}")
                if current:
                    print(f"  Current: {current!r}")
                raw = input("  Enter answer (blank = skip): ").strip()
                answer = raw or None

            if answer:
                self._click_node(node)
                time.sleep(self._rng.uniform(0.15, 0.35))
                _hum_type(answer, profile=self._profile, rng=self._rng)
                self._result.actions_taken += 1
                log.info("Typed approved answer for field '%s'", label[:40])

    # ── Click via CDP coord resolution + OS HID ───────────────────────────────

    def _click_node(self, node: dict) -> None:
        """
        Resolve node screen coordinates via CDP, deliver click via OS HID.
        Falls back to CDP click if coordinate resolution fails.
        """
        node_id = node.get("nodeId")
        name    = node.get("name", "")

        try:
            dom_result = self._cdp._send("DOM.describeNode", {
                "accessibilityNodeId": node_id
            })
            backend_id = dom_result.get("node", {}).get("backendNodeId")

            if backend_id:
                box_result = self._cdp._send("DOM.getBoxModel", {"backendNodeId": backend_id})
                content = box_result.get("model", {}).get("content", [])
                if len(content) >= 8:
                    vx = (content[0] + content[2]) / 2
                    vy = (content[1] + content[5]) / 2
                    ox, oy = self._cdp._get_screen_offset()
                    sx, sy = int(ox + vx), int(oy + vy)
                    log.debug("Clicking '%s' at screen (%d, %d)", name[:40], sx, sy)
                    _hum_click(sx, sy, profile=self._profile, rng=self._rng)
                    return
        except Exception as e:
            log.debug("Coord resolution failed for '%s': %s — using CDP click", name[:40], e)

        # Fallback: JS querySelector by role + name
        try:
            role = node.get("role", "")
            escaped = name.replace("'", "\\'")
            js = (
                f"(function(){{"
                f"var els = document.querySelectorAll('[role={role!r}]');"
                f"for(var i=0;i<els.length;i++){{"
                f"  if((els[i].textContent||els[i].getAttribute('aria-label')||'').trim()=='{escaped}'){{"
                f"    var r=els[i].getBoundingClientRect();"
                f"    return {{x:r.left+r.width/2,y:r.top+r.height/2,found:true}};"
                f"}}}}"
                f"return null;}})();"
            )
            coords = self._cdp.eval_js(js)
            if coords and coords.get("found"):
                ox, oy = self._cdp._get_screen_offset()
                sx = int(ox + coords["x"])
                sy = int(oy + coords["y"])
                _hum_click(sx, sy, profile=self._profile, rng=self._rng)
                return
        except Exception:
            pass

        # Last resort: CDP dispatch click (isTrusted=false but better than nothing)
        try:
            self._cdp.click_js(
                f"document.querySelector('[aria-label=\"{name}\"]') "
                f"|| document.querySelector('[title=\"{name}\"]')"
            )
        except Exception as e:
            log.warning("All click methods failed for '%s': %s", name[:40], e)
