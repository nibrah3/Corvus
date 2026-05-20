# navigator.py — Phase 10: SOP Navigator
# SCHEMA_VERSION: 1
#
# Single responsibility: execute a SOP to navigate the assessment UI.
# Implements NavigatorFn = Callable[[SOP, CaptureSession, Profile], bool]
#
# Formal constraint: one code path per step — no branching, no popup handling,
# no recursive retries. Return False on first failure. Never writes FSM state.
#
# MUST NOT: interpret question content, modify FSM state, build answers.

from __future__ import annotations

import time
import uuid
from typing import Callable, Optional

from .actions import dispatch
from .capture import CaptureFrame, CaptureSession
from .errors import CaptureError
from .perception.frame_diff import compute_diff
from .perception.ocr import extract_ocr_elements
from .perception.uia import extract_uia_elements
from .schema import Action, Profile, SOP, SOPStep, UIElement
from .types import ChangeType

# ── Timing constants ──────────────────────────────────────────────────────────

_STEP_SETTLE_S:   float = 5.0   # max seconds to wait for UI to settle after a step
_POLL_INTERVAL_S: float = 0.25  # seconds between settle-check grabs

# ── NavigatorFn type alias ────────────────────────────────────────────────────

NavigatorFn = Callable[["SOP", "CaptureSession", "Profile"], bool]


# ── Internal helpers ──────────────────────────────────────────────────────────

def _find_by_anchor(
    anchor_text: str,
    window_title: str,
    session: CaptureSession,
) -> Optional[UIElement]:
    """
    Locate the first element whose text contains anchor_text (case-insensitive).
    UIA first (native controls); OCR fallback on the full window region.
    Returns the matching UIElement, or None if not found.
    """
    try:
        frame = session.grab(window_title)
    except CaptureError:
        return None

    # UIA pass — native controls, zero pixel cost
    try:
        for elem in extract_uia_elements(window_title, frame_id=frame.frame_id):
            if anchor_text.lower() in elem.text.lower():
                return elem
    except Exception:
        pass

    # OCR fallback — full window region
    try:
        for elem in extract_ocr_elements(frame, regions=(frame.window_bbox,)):
            if anchor_text.lower() in elem.text.lower():
                return elem
    except Exception:
        pass

    return None


def _wait_settle(
    window_title: str,
    session: CaptureSession,
    timeout_s: float,
) -> bool:
    """
    Poll until frame diff is NONE or MINOR (UI has settled after an action).
    Returns True when stable, False on capture failure or timeout.
    """
    deadline = time.monotonic() + timeout_s
    last_frame: Optional[CaptureFrame] = None

    while time.monotonic() < deadline:
        try:
            frame = session.grab(window_title)
        except CaptureError:
            return False

        if last_frame is not None:
            diff = compute_diff(last_frame, frame)
            if diff.change_type in (ChangeType.NONE, ChangeType.MINOR):
                return True

        last_frame = frame
        time.sleep(_POLL_INTERVAL_S)

    return False


def _execute_step(
    step: SOPStep,
    window_title: str,
    session: CaptureSession,
    profile: Profile,
) -> bool:
    """
    Execute one SOP step: locate anchor → dispatch action → wait for UI settle.
    Returns True on success, False on any failure.
    One code path — no retries, no branching.
    """
    elem = _find_by_anchor(step.anchor_text, window_title, session)
    if elem is None:
        return False

    action = Action(
        action_id=f"nav-{uuid.uuid4().hex[:8]}",
        action_type=step.action_type,
        target_element_id=elem.element_id,
        payload=dict(step.payload),
        profile_id=profile.profile_id,
        frame_id=elem.frame_id,
    )

    result = dispatch(action, elem.bbox, profile.behavior)
    if not result.success:
        return False

    return _wait_settle(window_title, session, _STEP_SETTLE_S)


# ── Public API ────────────────────────────────────────────────────────────────

def navigate(
    sop: SOP,
    session: CaptureSession,
    profile: Profile,
    window_title: str,
) -> bool:
    """
    Execute all SOP steps in order.
    Returns True if every step completes, False on the first failure.
    Not a NavigatorFn directly — use make_navigator() to inject window_title.
    """
    for step in sop.steps:
        if not _execute_step(step, window_title, session, profile):
            return False
    return True


def make_navigator(window_title: str) -> NavigatorFn:
    """
    Return a NavigatorFn that binds window_title for injection into AssessmentOrchestrator.
    """
    def _fn(sop: SOP, session: CaptureSession, profile: Profile) -> bool:
        return navigate(sop, session, profile, window_title)
    return _fn
