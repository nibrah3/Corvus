# orchestrator.py — Phase 8: Assessment Execution Loop
# SCHEMA_VERSION: 1
#
# Single responsibility: drive one assessment run from INIT to COMPLETE
# by wiring capture → diff → perceive → FSM → act.
#
# This is the ONLY module permitted to call across layer boundaries.
# All other modules are single-layer.
#
# LLM reasoning (REASON state) and SOP navigation (NAVIGATE state) are
# injected as callables — stub them out in tests, wire real impls in Phase 9.
#
# MUST NOT: interpret pixel content, build answers, record SOPs.

from __future__ import annotations

import random
import time
from typing import Callable, Optional

import pyautogui

from .capture import CaptureFrame, CaptureSession
from .errors import CaptureError, ErrorCode, PerceptionError, StateError
from .fsm import AssessmentFSM, FSMTransition
from .perception.frame_diff import FrameDiff, compute_diff
from .perception.ocr import extract_ocr_elements
from .perception.uia import extract_uia_elements
from .schema import Action, BoundingBox, Profile, SOP, UIElement, UIState
from .states import EXECUTION_STATES, PERCEPTION_STATES, REASONING_STATES
from .types import ActionType, ChangeType, ConfidenceBand, FSMState, confidence_band

_SCROLL_MARGIN_PX: int = 80    # keep element this far from screen edge after scroll
_PX_PER_SCROLL_CLICK: int = 100  # approximate browser pixels scrolled per wheel click

# ── Timing constants ──────────────────────────────────────────────────────────

LOOP_TIMEOUT_S:    float = 300.0   # max seconds for a full assessment run
WAIT_UI_TIMEOUT_S: float = 30.0    # max seconds waiting for UI to settle
POLL_INTERVAL_S:   float = 0.5     # seconds between capture polls


# ── Callable type aliases (injected dependencies) ─────────────────────────────

# reasoner(ui_state, profile) → list of Actions to execute
ReasonerFn = Callable[["UIState", Profile], list[Action]]

# navigator(sop, session, profile) → True if navigation succeeded
NavigatorFn = Callable[[SOP, "CaptureSession", Profile], bool]


# ── UIState builder ───────────────────────────────────────────────────────────

def _build_ui_state(
    frame: CaptureFrame,
    uia_elements: list[UIElement],
    ocr_elements: list[UIElement],
) -> UIState:
    """Merge UIA and OCR elements into a UIState for this frame."""
    all_elements = tuple(uia_elements + ocr_elements)
    return UIState(
        frame_id=frame.frame_id,
        timestamp=frame.timestamp,
        window_title=frame.window_title,
        window_bbox=frame.window_bbox,
        elements=all_elements,
    )


# ── AssessmentOrchestrator ────────────────────────────────────────────────────

class AssessmentOrchestrator:
    """
    Drives one assessment run: INIT → NAVIGATE → WAIT_UI → EXTRACT →
    REASON → EXECUTE → VERIFY → COMPLETE.

    Usage:
        orch = AssessmentOrchestrator(
            window_title="IXBrowser",
            profile=profile,
            reasoner=my_llm_reasoner,
        )
        final_state = orch.run()

    dry_run=True: actions are computed but not executed (for testing).
    reasoner/navigator=None: those states immediately error unless the FSM
        context already has what they need (useful for unit tests).
    """

    def __init__(
        self,
        window_title: str,
        profile: Profile,
        sop: Optional[SOP] = None,
        reasoner: Optional[ReasonerFn] = None,
        navigator: Optional[NavigatorFn] = None,
        dry_run: bool = False,
        loop_timeout_s: float = LOOP_TIMEOUT_S,
        wait_ui_timeout_s: float = WAIT_UI_TIMEOUT_S,
        poll_interval_s: float = POLL_INTERVAL_S,
    ) -> None:
        self._window_title = window_title
        self._profile = profile
        self._sop = sop
        self._reasoner = reasoner
        self._navigator = navigator
        self._dry_run = dry_run
        self._loop_timeout_s = loop_timeout_s
        self._wait_ui_timeout_s = wait_ui_timeout_s
        self._poll_interval_s = poll_interval_s
        self.fsm = AssessmentFSM(profile.profile_id)

    # ── Public entry point ────────────────────────────────────────────────────

    def run(self) -> FSMState:
        """
        Run the assessment loop until a terminal state or timeout.
        Returns the final FSMState (COMPLETE or ERROR).
        """
        try:
            with CaptureSession() as session:
                return self._loop(session)
        except Exception as e:
            if not self.fsm.is_terminal():
                self.fsm.to_error(f"unhandled exception in run(): {e}")
            return self.fsm.state

    # ── Main loop ─────────────────────────────────────────────────────────────

    def _loop(self, session: CaptureSession) -> FSMState:
        deadline = time.monotonic() + self._loop_timeout_s
        last_frame: Optional[CaptureFrame] = None

        self.fsm.transition(FSMState.NAVIGATE, "assessment started")

        while not self.fsm.is_terminal():
            if time.monotonic() > deadline:
                self.fsm.to_error("loop timeout exceeded")
                break

            try:
                state = self.fsm.state

                if state == FSMState.NAVIGATE:
                    last_frame = self._handle_navigate(session, last_frame)

                elif state == FSMState.WAIT_UI:
                    last_frame = self._handle_wait_ui(session, last_frame, deadline)

                elif state == FSMState.EXTRACT:
                    last_frame = self._handle_extract(session, last_frame)

                elif state == FSMState.REASON:
                    self._handle_reason()

                elif state == FSMState.EXECUTE:
                    self._handle_execute(session)

                elif state == FSMState.VERIFY:
                    self._handle_verify()

                else:
                    break  # unhandled state — should not happen

            except StateError as e:
                self.fsm.to_error(f"state error: {e}")
            except Exception as e:
                self.fsm.to_error(f"unhandled error in {self.fsm.state.value}: {e}")

        return self.fsm.state

    # ── State handlers ────────────────────────────────────────────────────────

    def _handle_navigate(
        self,
        session: CaptureSession,
        last_frame: Optional[CaptureFrame],
    ) -> Optional[CaptureFrame]:
        """
        NAVIGATE: follow the SOP to reach the question page, or skip if no SOP.
        Transitions to WAIT_UI on success, ERROR on failure.
        """
        if self._sop is not None and self._navigator is not None:
            try:
                ok = self._navigator(self._sop, session, self._profile)
                if not ok:
                    self.fsm.to_error("navigator returned False")
                    return last_frame
            except Exception as e:
                self.fsm.to_error(f"navigator raised: {e}")
                return last_frame

        # No SOP / no navigator → assume we're already on the right page
        self.fsm.transition(FSMState.WAIT_UI, "navigation complete (no SOP)")
        return last_frame

    def _handle_wait_ui(
        self,
        session: CaptureSession,
        last_frame: Optional[CaptureFrame],
        global_deadline: float,
    ) -> Optional[CaptureFrame]:
        """
        WAIT_UI: poll until the frame diff falls to NONE/MINOR (UI settled).
        Transitions to EXTRACT on stable, ERROR on timeout.
        """
        wait_deadline = min(
            time.monotonic() + self._wait_ui_timeout_s,
            global_deadline,
        )

        while time.monotonic() < wait_deadline:
            try:
                frame = session.grab(self._window_title)
            except CaptureError as e:
                self.fsm.to_error(f"capture failed in WAIT_UI: {e}")
                return last_frame

            if last_frame is not None:
                diff = compute_diff(last_frame, frame)
                if diff.change_type in (ChangeType.NONE, ChangeType.MINOR):
                    # UI has settled
                    self.fsm.set_context("last_diff", diff)
                    last_frame = frame
                    self.fsm.transition(FSMState.EXTRACT, "UI settled")
                    return last_frame
            else:
                # First frame — can't diff yet, just wait one more poll
                pass

            last_frame = frame
            # Gaussian jitter: prevents perfectly rhythmic polling patterns
            # that anti-bot systems flag as automation signatures.
            jitter = random.gauss(0, self._poll_interval_s * 0.2)
            time.sleep(max(0.05, self._poll_interval_s + jitter))

        self.fsm.to_error("WAIT_UI timeout: UI did not settle")
        return last_frame

    def _handle_extract(
        self,
        session: CaptureSession,
        last_frame: Optional[CaptureFrame],
    ) -> Optional[CaptureFrame]:
        """
        EXTRACT: grab frame, run UIA + OCR on dirty regions, build UIState.
        Stores ui_state in context. Transitions to REASON on success.
        """
        try:
            frame = session.grab(self._window_title)
        except CaptureError as e:
            self.fsm.to_error(f"capture failed in EXTRACT: {e}")
            return last_frame

        # Determine dirty regions: use last diff if available, else full window
        diff: Optional[FrameDiff] = self.fsm.get_context("last_diff")
        if diff is not None and diff.dirty_regions:
            regions = diff.dirty_regions
        else:
            regions = (frame.window_bbox,)

        # UIA: native controls (tolerates failure)
        uia_elements: list[UIElement] = []
        try:
            uia_elements = extract_uia_elements(
                self._window_title,
                frame_id=frame.frame_id,
            )
        except Exception:
            pass  # UIA unavailable or window not accessible — OCR will cover it

        # OCR: text in dirty regions
        ocr_elements: list[UIElement] = []
        try:
            ocr_elements = extract_ocr_elements(frame, regions=regions)
        except Exception:
            pass  # OCR unavailable — degrade gracefully

        raw_state = _build_ui_state(frame, uia_elements, ocr_elements)

        # Confidence band gating: discard LOW-confidence elements before reasoning
        usable = tuple(
            e for e in raw_state.elements
            if confidence_band(e.confidence) != ConfidenceBand.LOW
        )
        # Only error when elements were detected but ALL failed the confidence gate.
        # Zero elements passes through — reasoner returns [] and FSM routes to COMPLETE.
        if raw_state.elements and not usable:
            self.fsm.to_error(
                f"EXTRACT: all {len(raw_state.elements)} elements below confidence threshold"
            )
            return frame

        n_filtered = len(raw_state.elements) - len(usable)
        if n_filtered:
            ui_state = UIState(
                frame_id=raw_state.frame_id,
                timestamp=raw_state.timestamp,
                window_title=raw_state.window_title,
                window_bbox=raw_state.window_bbox,
                elements=usable,
            )
            suffix = f" ({n_filtered} low-confidence filtered)"
        else:
            ui_state = raw_state
            suffix = ""

        self.fsm.set_context("ui_state", ui_state)
        self.fsm.transition(FSMState.REASON, f"extracted {len(usable)} elements{suffix}")
        return frame

    def _handle_reason(self) -> None:
        """
        REASON: call the reasoner with current UIState + profile to get actions.
        Stores pending_actions in context. Transitions to EXECUTE.
        If no reasoner: transitions to COMPLETE (nothing to do).
        """
        if self._reasoner is None:
            # No reasoner — nothing to execute. Route through EXECUTE→VERIFY→COMPLETE
            # (REASON→COMPLETE is not a valid transition per states.py).
            self.fsm.set_context("pending_actions", [])
            self.fsm.set_context("action_index", 0)
            self.fsm.transition(FSMState.EXECUTE, "no reasoner — skipping to execute")
            return

        ui_state: Optional[UIState] = self.fsm.get_context("ui_state")
        if ui_state is None:
            self.fsm.to_error("REASON entered without ui_state in context")
            return

        try:
            actions = self._reasoner(ui_state, self._profile)
        except Exception as e:
            self.fsm.to_error(f"reasoner raised: {e}")
            return

        self.fsm.set_context("pending_actions", list(actions))
        self.fsm.set_context("action_index", 0)

        self.fsm.transition(FSMState.EXECUTE, f"reasoner produced {len(actions)} actions")

    def _scroll_into_view(
        self,
        session: CaptureSession,
        bbox: BoundingBox,
        target_text: str,
    ) -> Optional[BoundingBox]:
        """
        If bbox is off-screen, scroll to bring it into view and return the
        updated bbox by re-running OCR and matching on text.
        Returns original bbox if already in view, updated bbox after scroll,
        or None if re-OCR couldn't locate the element.
        """
        _, screen_h = pyautogui.size()
        elem_bottom = bbox.y + bbox.h
        elem_top    = bbox.y

        needs_scroll_down = elem_bottom > screen_h - _SCROLL_MARGIN_PX
        needs_scroll_up   = elem_top < _SCROLL_MARGIN_PX

        if not needs_scroll_down and not needs_scroll_up:
            return bbox  # already in view

        # Move mouse to window centre before scrolling so the scroll lands in-page
        try:
            frame = session.grab(self._window_title)
            win   = frame.window_bbox
            pyautogui.moveTo(win.x + win.w // 2, win.y + win.h // 2, duration=0.1)
        except Exception:
            pass

        if needs_scroll_down:
            scroll_px     = elem_bottom - (screen_h - _SCROLL_MARGIN_PX)
            scroll_clicks = max(1, round(scroll_px / _PX_PER_SCROLL_CLICK))
            pyautogui.scroll(-scroll_clicks)
        else:
            scroll_px     = _SCROLL_MARGIN_PX - elem_top
            scroll_clicks = max(1, round(scroll_px / _PX_PER_SCROLL_CLICK))
            pyautogui.scroll(scroll_clicks)

        print(f"[execute] scrolled {'down' if needs_scroll_down else 'up'} {scroll_clicks} clicks to reach '{target_text[:40]}'", flush=True)
        time.sleep(0.6)  # wait for scroll animation to settle

        # Re-capture and re-OCR to find updated element position
        try:
            frame = session.grab(self._window_title)
            ocr_elements = extract_ocr_elements(frame, regions=(frame.window_bbox,))
            uia_elements = extract_uia_elements(self._window_title, frame_id=frame.frame_id)
        except Exception:
            return None

        needle = target_text.strip().lower()
        for elem in ocr_elements + uia_elements:
            if elem.text.strip().lower() == needle:
                print(f"[execute] re-found '{target_text[:40]}' at y={elem.bbox.y}", flush=True)
                return elem.bbox

        return None  # element not found after scroll

    def _handle_execute(self, session: CaptureSession) -> None:
        """
        EXECUTE: dispatch the next pending action.
        Transitions to VERIFY after each action (success or failure).
        """
        from .actions import dispatch

        pending: list[Action] = self.fsm.get_context("pending_actions", [])
        idx: int = self.fsm.get_context("action_index", 0)

        if idx >= len(pending):
            self.fsm.transition(FSMState.VERIFY, "all actions dispatched")
            return

        action = pending[idx]

        # Resolve the target element's bbox and text from ui_state
        ui_state: Optional[UIState] = self.fsm.get_context("ui_state")
        bbox: Optional[BoundingBox] = None
        target_text: str = ""
        if ui_state is not None:
            for elem in ui_state.elements:
                if elem.element_id == action.target_element_id:
                    bbox        = elem.bbox
                    target_text = elem.text
                    break

        if bbox is None:
            self.fsm.to_error(
                f"target element {action.target_element_id!r} not found in ui_state"
            )
            return

        # Scroll element into view if it's off-screen; update bbox with post-scroll position
        if not self._dry_run:
            updated = self._scroll_into_view(session, bbox, target_text)
            if updated is not None:
                bbox = updated
            elif updated is None and (bbox.y > pyautogui.size()[1] or bbox.y + bbox.h > pyautogui.size()[1]):
                self.fsm.to_error(
                    f"element '{target_text[:40]}' could not be scrolled into view"
                )
                return

        # Pre-action snapshot for post-dispatch change verification (CLICK only)
        pre_snap: Optional[CaptureFrame] = None
        if not self._dry_run and action.action_type == ActionType.CLICK:
            try:
                pre_snap = session.grab(self._window_title)
            except Exception:
                pass

        result = dispatch(action, bbox, self._profile.behavior, dry_run=self._dry_run)
        self.fsm.set_context("last_action_result", result)
        self.fsm.set_context("last_action_type", action.action_type)
        self.fsm.set_context("action_index", idx + 1)

        # Post-action snapshot: compute diff and store ChangeType for verify
        if pre_snap is not None and result.success:
            try:
                post_snap = session.grab(self._window_title)
                diff = compute_diff(pre_snap, post_snap)
                self.fsm.set_context("last_action_change_type", diff.change_type)
            except Exception:
                self.fsm.set_context("last_action_change_type", None)
        else:
            self.fsm.set_context("last_action_change_type", None)

        self.fsm.transition(FSMState.VERIFY, f"action {action.action_id} dispatched")

    def _handle_verify(self) -> None:
        """
        VERIFY: check the last action result and decide what to do next.

        - Action failed → ERROR
        - More actions pending → EXECUTE
        - All actions done → NAVIGATE (next question) or COMPLETE
        """
        from .actions import ActionResult

        result: Optional[ActionResult] = self.fsm.get_context("last_action_result")
        if result is not None and not result.success:
            self.fsm.to_error(
                f"action failed: {result.error_message or result.error_code}"
            )
            return

        # Verify CLICK produced a UI change — ChangeType.NONE means the target
        # did not respond (element not interactive, already-selected state, etc.)
        last_action_type  = self.fsm.get_context("last_action_type")
        last_change_type  = self.fsm.get_context("last_action_change_type")
        if (
            last_action_type == ActionType.CLICK
            and last_change_type == ChangeType.NONE
        ):
            self.fsm.to_error("click action produced no UI change — verify failed")
            return

        pending: list[Action] = self.fsm.get_context("pending_actions", [])
        idx: int = self.fsm.get_context("action_index", 0)

        if idx < len(pending):
            # More actions to execute for this question
            self.fsm.transition(FSMState.EXECUTE, "more actions pending")
        else:
            # All actions done — decide if there are more questions
            more_questions: bool = self.fsm.get_context("more_questions", False)
            if more_questions:
                # Clear per-question context before navigating to next
                self.fsm.clear_context("ui_state")
                self.fsm.clear_context("pending_actions")
                self.fsm.clear_context("action_index")
                self.fsm.clear_context("last_action_result")
                self.fsm.clear_context("last_diff")
                self.fsm.transition(FSMState.NAVIGATE, "moving to next question")
            else:
                self.fsm.transition(FSMState.COMPLETE, "all questions answered")
