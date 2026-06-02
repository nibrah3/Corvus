"""
annotation_pipeline.py — Image and video annotation task automation.

Architecture:
  Perception  → CDPExecutor (read DOM: task question, options, media URL)
  Vision      → gemini_vision (Gemini Flash via OpenRouter — image URL inline,
                               no download into browser, no tab activity)
  Execution   → humanizer_mcp OS HID (pynput) — isTrusted=true clicks, stealth

Stealth contract:
  Everything Gemini-related happens in the Python process.
  The browser tab only sees: idle → one click on an answer → idle → advance.
  No tab blur, no clipboard, no JS fetch, no new network requests from the tab.
  Gemini fetches the image URL from the CDN externally, invisible to the page.

Supported platforms:
  - Zooniverse (Galaxy Zoo image classification)
  - Generic (any MCQ annotation platform with accessible DOM)

Usage:
    from careerbridge.annotation_pipeline import AnnotationPipeline, AnnotationConfig
    from careerbridge.ixbrowser_connector import ix_open_profile

    cdp_url = ix_open_profile(12)
    cfg = AnnotationConfig(
        cdp_url=cdp_url,
        url="https://www.zooniverse.org/projects/zookeeper/galaxy-zoo/classify",
        task_type="image",
        platform="zooniverse",
        max_tasks=10,
    )
    result = AnnotationPipeline(cfg).run()
"""
from __future__ import annotations

import logging
import os
import random
import sys
import time
from dataclasses import dataclass
from typing import Any, Optional

CB_DIR = os.path.normpath(os.path.join(os.path.dirname(__file__), ".."))
if CB_DIR not in sys.path:
    sys.path.insert(0, CB_DIR)

from careerbridge.cdp_executor import CDPExecutor, CDPError
from humanizer_mcp._mouse   import click as _hum_click
from humanizer_mcp._profile import BehaviorProfile

log = logging.getLogger(__name__)

_SUBMIT_NAMES = frozenset({"done", "next", "continue", "submit", "classify", "finish"})


@dataclass
class AnnotationConfig:
    cdp_url:        str
    url:            str
    task_type:      str   = "image"     # "image" or "video"
    platform:       str   = "generic"   # "zooniverse" or "generic"
    max_tasks:      int   = 20
    task_timeout_s: float = 30.0
    profile_seed:   Optional[int] = None
    profile:        Any   = None        # optional candidate profile for logging


@dataclass
class AnnotationResult:
    ok:            bool
    tasks_done:    int  = 0
    llm_calls:     int  = 0
    actions_taken: int  = 0
    error:         Optional[str] = None


class AnnotationPipeline:
    """Automate image/video annotation tasks on public platforms."""

    def __init__(self, config: AnnotationConfig) -> None:
        self._cfg     = config
        self._cdp     = CDPExecutor()
        self._profile = BehaviorProfile.default()
        self._rng     = random.Random(config.profile_seed)
        self._result  = AnnotationResult(ok=False)

    def run(self) -> AnnotationResult:
        try:
            # Step 1: Connect to whatever IXBrowser opened (newtab / default page)
            self._cdp.connect_ws(self._cfg.cdp_url)
            port = self._cdp._port

            # Step 2: Open the annotation URL in a BRAND NEW tab via Target API.
            # This avoids the cross-origin renderer-process transition that kills the
            # newtab WebSocket — we stay on the newtab session while the new tab loads.
            target_id: str = ""
            try:
                res       = self._cdp._send("Target.createTarget", {"url": self._cfg.url})
                target_id = res.get("targetId", "")
                log.info("Opened new target %s for %s", target_id[:12], self._cfg.url)
            except Exception as e:
                log.warning("Target.createTarget failed (%s) — falling back to navigate", e)

            if target_id:
                # Disconnect from newtab cleanly, then connect to the Zooniverse tab
                self._cdp.disconnect()
                time.sleep(1.5)
                page_ws = f"ws://127.0.0.1:{port}/devtools/page/{target_id}"
                self._cdp = CDPExecutor()
                self._cdp.connect_ws(page_ws)   # page-level URL → direct connect
            else:
                # Fallback: navigate in-place (cross-origin drop may occur)
                try:
                    self._cdp.navigate(self._cfg.url)
                except Exception:
                    pass

            # Step 3: Wait for the SPA to render
            time.sleep(6.0)
            try:
                self._cdp.wait_for_load(timeout=20.0)
            except Exception:
                pass

            self._loop()
            self._result.ok = True
        except Exception as e:
            self._result.error = str(e)
            log.error("Annotation pipeline failed: %s", e)
        finally:
            try:
                self._cdp.disconnect()
            except Exception:
                pass
        return self._result

    # ── Main loop ─────────────────────────────────────────────────────────────

    def _loop(self) -> None:
        from careerbridge.gemini_vision import (
            annotate_image, annotate_image_b64, annotate_video,
        )

        consecutive_empty = 0

        for task_num in range(1, self._cfg.max_tasks + 1):
            log.info("Annotation task %d/%d", task_num, self._cfg.max_tasks)

            if self._is_session_done():
                log.info("Session complete signal — stopping")
                break

            task = self._extract_task()
            if not task:
                consecutive_empty += 1
                if consecutive_empty >= 3:
                    log.info("3 consecutive empty tasks — login wall or no subjects, stopping")
                    break
                log.warning("Empty task %d/%d — retrying after pause", task_num, self._cfg.max_tasks)
                time.sleep(2.0)
                continue

            question  = task.get("question", "Classify this subject")
            options   = task.get("options", [])
            image_url = task.get("image_url", "")
            video_url = task.get("video_url", "")

            if not options:
                consecutive_empty += 1
                if consecutive_empty >= 3:
                    log.info("3 consecutive no-option tasks — login wall, stopping")
                    break
                log.warning("No options on task %d — advancing", task_num)
                self._advance()
                continue

            consecutive_empty = 0  # reset on successful task extraction

            log.info("Q: %r | Options: %s", question[:80], options)

            # Vision perception — all Python-side, invisible to tab
            answer: Optional[str] = None
            try:
                if self._cfg.task_type == "video" and video_url:
                    answer = annotate_video(video_url, question, options)
                elif image_url:
                    answer = annotate_image(image_url, question, options)
                else:
                    # No extractable URL — screenshot the visible page area
                    answer = self._annotate_from_screenshot(question, options)
                self._result.llm_calls += 1
            except Exception as e:
                log.warning("Gemini perception failed: %s — skipping task", e)

            log.info("Gemini answer: %r", answer)

            # Simulate thinking pause after seeing image (very fast human: 1.5–3s)
            time.sleep(max(1.2, min(3.5, self._rng.gauss(2.0, 0.5))))

            # Click the matching option
            if answer:
                clicked = self._select_option(answer, task.get("option_nodes", []))
                if clicked:
                    self._result.actions_taken += 1

            # Pause before advancing (reviewing selection)
            time.sleep(max(0.4, min(1.2, self._rng.gauss(0.7, 0.2))))
            self._advance()
            self._result.tasks_done += 1

            # Wait for next task to load
            time.sleep(max(0.8, min(2.5, self._rng.gauss(1.5, 0.4))))

    # ── Task extraction ───────────────────────────────────────────────────────

    def _extract_task(self) -> Optional[dict]:
        try:
            if self._cfg.platform == "zooniverse":
                return self._extract_zooniverse()
            return self._extract_generic()
        except Exception as e:
            log.warning("Task extraction error: %s", e)
            return None

    def _extract_zooniverse(self) -> Optional[dict]:
        # Question text
        question = self._cdp.eval_js(
            "var sel = ["
            "  '[class*=\"task-question\"]',"
            "  '[class*=\"TaskText\"]',"
            "  '[class*=\"question-text\"]',"
            "  'h2.question',"
            "  '[data-testid=\"task-question\"]',"
            "].join(',');"
            "var el = document.querySelector(sel);"
            "el ? el.innerText.trim() : ''"
        ) or "Classify this galaxy"

        # Image URL — Zooniverse uses SVG <image xlink:href> or standard <img>
        image_url = self._cdp.eval_js("""
            (function() {
                var svgImg = document.querySelector('svg image');
                if (svgImg) {
                    return svgImg.getAttribute('href')
                        || svgImg.getAttribute('xlink:href')
                        || svgImg.getAttribute('src')
                        || '';
                }
                var img = document.querySelector(
                    '.subject img, [class*="subject"] img, '
                    + 'img[class*="Subject"], img[class*="subject-image"]'
                );
                if (img) return img.src || '';
                return '';
            })()
        """) or ""

        # Options — answer/choice buttons
        raw_opts = self._cdp.eval_js("""
            Array.from(document.querySelectorAll(
                '[class*="answer"], [class*="Answer"], '
                + '[class*="choice"], [class*="Choice"], '
                + 'button.answer, [role="radio"]'
            ))
            .filter(function(el) {
                var t = (el.innerText || el.getAttribute('aria-label') || '').trim();
                return t.length > 0 && t.length < 120;
            })
            .map(function(el) {
                return {
                    text: (el.innerText || el.getAttribute('aria-label') || '').trim(),
                    id:   el.id || ''
                };
            })
        """) or []

        if not raw_opts:
            return self._extract_generic()

        opts = [o["text"] for o in raw_opts if isinstance(o, dict) and o.get("text")]
        return {
            "question":     question,
            "image_url":    image_url,
            "video_url":    "",
            "options":      opts,
            "option_nodes": raw_opts,
        }

    def _extract_generic(self) -> Optional[dict]:
        question = self._cdp.eval_js(
            "(function() {"
            "  var tags = document.querySelectorAll('h1,h2,h3,[class*=\"question\"],[class*=\"task\"]');"
            "  for (var i = 0; i < tags.length; i++) {"
            "    var t = tags[i].innerText.trim();"
            "    if (t.length > 5 && t.length < 500) return t;"
            "  }"
            "  return '';"
            "})()"
        ) or "Classify"

        # Largest non-icon image on page
        image_url = self._cdp.eval_js("""
            (function() {
                var imgs = Array.from(document.querySelectorAll('img'))
                    .filter(function(i) {
                        return i.naturalWidth  > 100
                            && i.naturalHeight > 100
                            && !/logo|icon|avatar|badge/i.test(i.src);
                    })
                    .sort(function(a, b) {
                        return (b.naturalWidth * b.naturalHeight)
                             - (a.naturalWidth * a.naturalHeight);
                    });
                return imgs.length ? imgs[0].src : '';
            })()
        """) or ""

        raw_opts = self._cdp.eval_js("""
            Array.from(document.querySelectorAll(
                'button, [role="button"], [role="radio"], label'
            ))
            .filter(function(el) {
                var t = el.innerText.trim();
                return t.length > 0 && t.length < 100
                    && !/^(next|previous|back|skip|submit|done|cancel)$/i.test(t);
            })
            .slice(0, 12)
            .map(function(el) {
                return { text: el.innerText.trim(), id: el.id || '' };
            })
        """) or []

        opts = [o["text"] for o in raw_opts if isinstance(o, dict) and o.get("text")]
        return {
            "question":     question,
            "image_url":    image_url,
            "video_url":    "",
            "options":      opts,
            "option_nodes": raw_opts,
        }

    # ── Fallback: screenshot perception ───────────────────────────────────────

    def _annotate_from_screenshot(self, question: str, options: list[str]) -> Optional[str]:
        """CDP screenshot → base64 → Gemini. Used when image URL is not extractable."""
        from careerbridge.gemini_vision import annotate_image_b64
        try:
            result = self._cdp._send("Page.captureScreenshot",
                                     {"format": "jpeg", "quality": 75})
            b64 = result.get("data", "")
            if not b64:
                return None
            return annotate_image_b64(b64, "image/jpeg", question, options)
        except Exception as e:
            log.warning("Screenshot fallback failed: %s", e)
            return None

    # ── Option selection ──────────────────────────────────────────────────────

    def _select_option(self, answer: str, option_nodes: list[dict]) -> bool:
        """Click the DOM button/radio that matches the Gemini answer."""
        answer_lower = answer.lower().strip()

        # Accessibility tree match — use OS HID for isTrusted=true click
        tree = self._cdp.get_axtree()
        for node in tree:
            role = (node.get("role") or "").lower()
            name = (node.get("name") or "").lower().strip()
            if role in ("button", "radio", "option", "menuitem", "tab", "checkbox"):
                if answer_lower in name or name in answer_lower:
                    self._click_node(node)
                    return True

        # Coordinate fallback — find element by text, get bounding rect, OS HID click.
        # Never fires el.click() (isTrusted=false). If coords can't be resolved, log and skip.
        safe_dq = answer.replace("\\", "\\\\").replace('"', '\\"')
        coords = self._cdp.eval_js(
            f"(function(){{"
            f"var els = Array.from(document.querySelectorAll("
            f"  'button,[role=radio],[role=option],label'));"
            f"var el = els.find(function(e){{"
            f"  return (e.innerText||'').trim().toLowerCase().includes(\"{safe_dq.lower()}\");"
            f"}});"
            f"if(!el) return null;"
            f"var r=el.getBoundingClientRect();"
            f"return {{x:r.left+r.width/2,y:r.top+r.height/2,found:true}};"
            f"}})()"
        )
        if coords and coords.get("found"):
            ox, oy = self._cdp._get_screen_offset()
            _hum_click(int(ox + coords["x"]), int(oy + coords["y"]),
                       profile=self._profile, rng=self._rng)
            return True
        log.warning("Could not resolve OS click coords for answer %r — skipping", answer[:40])
        return False

    # ── Advance to next task ──────────────────────────────────────────────────

    def _advance(self) -> None:
        """Click Done / Next / Continue to move to the next annotation task."""
        tree = self._cdp.get_axtree()
        for kw in ("done", "next", "continue", "submit", "classify"):
            for node in tree:
                if kw in (node.get("name") or "").lower():
                    role = (node.get("role") or "").lower()
                    if role in ("button", "link", "menuitem"):
                        self._click_node(node)
                        return

        # Coordinate fallback — resolve button center via getBoundingClientRect, OS HID click.
        coords = self._cdp.eval_js(
            "(function(){"
            "var btns = document.querySelectorAll('button');"
            "for (var i = 0; i < btns.length; i++) {"
            "  var t = btns[i].innerText.toLowerCase().trim();"
            "  if (t==='done'||t==='next'||t==='continue') {"
            "    var r=btns[i].getBoundingClientRect();"
            "    return {x:r.left+r.width/2,y:r.top+r.height/2,found:true};"
            "  }"
            "}"
            "return null;})()"
        )
        if coords and coords.get("found"):
            ox, oy = self._cdp._get_screen_offset()
            _hum_click(int(ox + coords["x"]), int(oy + coords["y"]),
                       profile=self._profile, rng=self._rng)
        else:
            log.warning("Advance: could not resolve Next/Done button coords via OS path")

    def _is_session_done(self) -> bool:
        try:
            text = (self._cdp.eval_js(
                "(document.body?.innerText||'').toLowerCase().slice(0,600)"
            ) or "")
            return any(kw in text for kw in [
                "session complete", "no more subjects", "all done",
                "you've finished", "thank you for contributing",
                "nothing left to classify",
            ])
        except Exception:
            return False

    # ── Click delivery ────────────────────────────────────────────────────────

    def _click_node(self, node: dict) -> None:
        """CDP bounding-box resolution + OS HID click (isTrusted=true)."""
        node_id = node.get("nodeId")
        name    = node.get("name", "")
        try:
            dom   = self._cdp._send("DOM.describeNode", {"accessibilityNodeId": node_id})
            bid   = dom.get("node", {}).get("backendNodeId")
            if bid:
                box = self._cdp._send("DOM.getBoxModel", {"backendNodeId": bid})
                c   = box.get("model", {}).get("content", [])
                if len(c) >= 8:
                    vx = (c[0] + c[2]) / 2
                    vy = (c[1] + c[5]) / 2
                    ox, oy = self._cdp._get_screen_offset()
                    _hum_click(int(ox + vx), int(oy + vy),
                               profile=self._profile, rng=self._rng)
                    return
        except Exception:
            pass

        # Coordinate fallback — getBoundingClientRect on role+name match, OS HID click.
        # Never calls el.click() — that would be isTrusted=false.
        try:
            role    = node.get("role", "button")
            esc_dq  = name.replace("\\", "\\\\").replace('"', '\\"')
            coords  = self._cdp.eval_js(
                f"(function(){{"
                f"var els=document.querySelectorAll('[role={role!r}],button');"
                f"for(var i=0;i<els.length;i++){{"
                f"  if((els[i].innerText||els[i].getAttribute('aria-label')||'').trim()==='{esc_dq}'){{"
                f"    var r=els[i].getBoundingClientRect();"
                f"    return {{x:r.left+r.width/2,y:r.top+r.height/2,found:true}};"
                f"  }}"
                f"}}return null;}})();"
            )
            if coords and coords.get("found"):
                ox, oy = self._cdp._get_screen_offset()
                _hum_click(int(ox + coords["x"]), int(oy + coords["y"]),
                           profile=self._profile, rng=self._rng)
                return
        except Exception:
            pass
        log.warning("All OS click paths failed for '%s' — element not reachable", name[:40])
