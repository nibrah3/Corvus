# actions.py — Action Layer (Phase 1)
# SCHEMA_VERSION: 1
#
# Single responsibility: OS-level mouse and keyboard execution.
#
# Receives: Action + resolved BoundingBox + BehaviorFingerprint
# Returns:  ActionResult
#
# MUST NOT: read screen, call OCR, call LLM, look up UIElements, decide what to click.
# Verification within this layer is mechanical only (did cursor arrive at target?).
# UI-state verification (did the radio button fill?) is the FSM's responsibility.

from __future__ import annotations

import math
import random
import time
from dataclasses import dataclass, field
from typing import Optional

import pyautogui
import pygetwindow as gw
from tenacity import retry, stop_after_attempt, wait_fixed, retry_if_exception_type

from .errors import ActionError, ErrorCode
from .schema import Action, BehaviorFingerprint, BoundingBox
from .types import ActionType, MouseSpeed

# ── pyautogui global config ───────────────────────────────────────────────────
# Disable pyautogui's built-in inter-call pause — we control all timing ourselves.
pyautogui.PAUSE = 0
# Keep failsafe enabled: moving to screen corner (0,0) raises FailSafeException.
pyautogui.FAILSAFE = True

# ── Constants ─────────────────────────────────────────────────────────────────
_BEZIER_STEPS: int = 40           # sample points along bezier curve
_POSITION_TOLERANCE_PX: int = 2   # acceptable landing error after mouse move
_MAX_RETRIES: int = 3

# WPM → ms per character: 1 word = 5 chars, so ms/char = 60_000 / (wpm * 5)
def _wpm_to_ms_per_char(wpm: int) -> float:
    return 60_000.0 / (wpm * 5)

# Mouse speed → movement duration in seconds
_MOUSE_DURATION: dict[MouseSpeed, float] = {
    MouseSpeed.SLOW:   0.55,
    MouseSpeed.MEDIUM: 0.32,
    MouseSpeed.FAST:   0.18,
}


# ── Result type ───────────────────────────────────────────────────────────────

@dataclass(frozen=True)
class ActionResult:
    success:       bool
    action_id:     str
    elapsed_ms:    float
    error_code:    Optional[ErrorCode] = None
    error_message: Optional[str]       = None


# ── Bezier internals ──────────────────────────────────────────────────────────

def _cubic_bezier(p0: float, p1: float, p2: float, p3: float, t: float) -> float:
    u = 1.0 - t
    return u**3 * p0 + 3*u**2*t * p1 + 3*u*t**2 * p2 + t**3 * p3


def _move_bezier(
    x0: int, y0: int,
    x1: int, y1: int,
    duration: float,
    dry_run: bool,
    rng: random.Random,
) -> None:
    """
    Move cursor from (x0,y0) to (x1,y1) along a cubic bezier curve.
    Control points are randomised per-call to produce human-like variation.
    In dry_run mode the path is computed but pyautogui is never called.
    """
    dist = math.hypot(x1 - x0, y1 - y0)
    jitter = max(10, int(dist * 0.25))

    cx1 = x0 + rng.randint(10, jitter) * rng.choice([-1, 1])
    cy1 = y0 + rng.randint(5,  jitter) * rng.choice([-1, 1])
    cx2 = x1 + rng.randint(10, jitter) * rng.choice([-1, 1])
    cy2 = y1 + rng.randint(5,  jitter) * rng.choice([-1, 1])

    step_delay = duration / _BEZIER_STEPS

    for i in range(_BEZIER_STEPS + 1):
        t = i / _BEZIER_STEPS
        px = int(_cubic_bezier(x0, cx1, cx2, x1, t))
        py = int(_cubic_bezier(y0, cy1, cy2, y1, t))
        if not dry_run:
            pyautogui.moveTo(px, py, _pause=False)
            time.sleep(step_delay)

    # Ensure exact landing regardless of rounding
    if not dry_run:
        pyautogui.moveTo(x1, y1, _pause=False)


def _verify_position(x: int, y: int) -> bool:
    """Verify cursor is within tolerance of expected landing point."""
    cx, cy = pyautogui.position()
    return abs(cx - x) <= _POSITION_TOLERANCE_PX and abs(cy - y) <= _POSITION_TOLERANCE_PX


# ── Core execution functions ──────────────────────────────────────────────────

def _execute_click(
    x: int,
    y: int,
    profile: BehaviorFingerprint,
    dry_run: bool,
    rng: random.Random,
) -> float:
    """
    Move to (x,y) via bezier, pause briefly, click, pause briefly.
    Returns elapsed milliseconds.
    Raises ActionError if cursor does not land within tolerance (non-dry_run only).
    """
    t0 = time.monotonic()
    duration = _MOUSE_DURATION[profile.mouse_speed]

    pre_pause  = rng.randint(80,  220) / 1000.0
    post_pause = rng.randint(120, 400) / 1000.0

    _move_bezier(
        *_get_current_pos(dry_run),
        x, y,
        duration=duration,
        dry_run=dry_run,
        rng=rng,
    )

    if not dry_run:
        time.sleep(pre_pause)
        pyautogui.click(x, y, _pause=False)
        time.sleep(post_pause)

        if not _verify_position(x, y):
            raise ActionError(
                ErrorCode.ACTION_CLICK_UNVERIFIED,
                f"Cursor landed outside tolerance after click at ({x},{y})",
                {"target_x": x, "target_y": y, "actual": list(pyautogui.position())},
            )

    return (time.monotonic() - t0) * 1000.0


def _execute_type(
    x: int,
    y: int,
    text: str,
    profile: BehaviorFingerprint,
    dry_run: bool,
    rng: random.Random,
) -> float:
    """
    Click the field at (x,y) then type text character-by-character with
    profile-driven WPM, gaussian timing jitter, and occasional typo+correction.
    Returns elapsed milliseconds.
    """
    t0 = time.monotonic()

    # Click field first
    _execute_click(x, y, profile, dry_run, rng)

    mean_delay    = _wpm_to_ms_per_char(profile.typing_wpm) / 1000.0
    std_delay     = mean_delay * 0.25
    min_delay     = mean_delay * 0.4
    max_delay     = mean_delay * 2.0

    for char in text:
        # Occasional typo: type a random neighbour key then backspace
        if rng.random() < profile.error_rate:
            wrong = chr(ord(char) + rng.choice([-1, 1]))
            if not dry_run:
                pyautogui.press(wrong, _pause=False)
            time.sleep(max(min_delay, min(max_delay, rng.gauss(mean_delay * 0.8, std_delay * 0.5))))
            if not dry_run:
                pyautogui.press("backspace", _pause=False)
            time.sleep(max(min_delay * 0.5, min(max_delay * 0.5, rng.gauss(mean_delay * 0.6, std_delay * 0.3))))

        if not dry_run:
            pyautogui.typewrite(char, interval=0, _pause=False)

        delay = max(min_delay, min(max_delay, rng.gauss(mean_delay, std_delay)))
        if not dry_run:
            time.sleep(delay)

    return (time.monotonic() - t0) * 1000.0


def _execute_scroll(
    x: int,
    y: int,
    direction: str,
    amount: int,
    dry_run: bool,
    rng: random.Random,
) -> float:
    """
    Move to (x,y) and scroll. Amount is varied ±10% for human-like behaviour.
    Returns elapsed milliseconds.
    """
    t0 = time.monotonic()

    _move_bezier(
        *_get_current_pos(dry_run),
        x, y,
        duration=0.25,
        dry_run=dry_run,
        rng=rng,
    )

    clicks = amount if direction == "down" else -amount
    # ±10% variation
    variation = rng.randint(-max(1, amount // 10), max(1, amount // 10))
    clicks += variation

    if not dry_run:
        pyautogui.scroll(clicks, x=x, y=y, _pause=False)

    return (time.monotonic() - t0) * 1000.0


def _get_current_pos(dry_run: bool) -> tuple[int, int]:
    if dry_run:
        return (0, 0)
    x, y = pyautogui.position()
    return (int(x), int(y))


# ── Window focus ──────────────────────────────────────────────────────────────

def focus_window(title: str) -> None:
    """
    Bring window matching title substring to foreground.
    Raises ActionError if window not found.
    """
    matches = [w for w in gw.getAllWindows() if title.lower() in w.title.lower()]
    if not matches:
        raise ActionError(
            ErrorCode.CAPTURE_WINDOW_NOT_FOUND,
            f"No window found matching title: {title!r}",
            {"title": title},
        )
    win = matches[0]
    try:
        win.activate()
    except Exception:
        # Some windows raise on activate() if already focused — ignore
        pass


# ── Public dispatch ───────────────────────────────────────────────────────────

def dispatch(
    action: Action,
    bbox: BoundingBox,
    profile: BehaviorFingerprint,
    dry_run: bool = False,
    _rng: Optional[random.Random] = None,
) -> ActionResult:
    """
    Execute one Action at the OS level.

    Args:
        action:   The Action to execute (from schema.py).
        bbox:     Resolved bounding box of the target UIElement (screen pixels).
        profile:  Candidate behavior fingerprint (controls timing + error rate).
        dry_run:  If True, compute paths and timing but do not call pyautogui.
        _rng:     Optional seeded Random for deterministic tests.

    Returns:
        ActionResult with success=True on completion, or success=False with
        error_code if execution failed after retries.

    Raises:
        ActionError only if retries are exhausted and the error is non-recoverable.
    """
    rng = _rng or random.Random()
    x, y = bbox.center_x, bbox.center_y

    try:
        elapsed = _dispatch_inner(action, x, y, profile, dry_run, rng)
        return ActionResult(
            success=True,
            action_id=action.action_id,
            elapsed_ms=elapsed,
        )
    except ActionError as e:
        return ActionResult(
            success=False,
            action_id=action.action_id,
            elapsed_ms=0.0,
            error_code=e.code,
            error_message=str(e),
        )


@retry(
    stop=stop_after_attempt(_MAX_RETRIES),
    wait=wait_fixed(0.1),
    retry=retry_if_exception_type(ActionError),
    reraise=True,
)
def _dispatch_inner(
    action: Action,
    x: int,
    y: int,
    profile: BehaviorFingerprint,
    dry_run: bool,
    rng: random.Random,
) -> float:
    t = action.action_type

    if t == ActionType.CLICK or t == ActionType.FOCUS:
        return _execute_click(x, y, profile, dry_run, rng)

    elif t == ActionType.TYPE:
        text = action.payload["text"]
        return _execute_type(x, y, text, profile, dry_run, rng)

    elif t == ActionType.SCROLL:
        direction = action.payload["direction"]
        amount    = action.payload["amount"]
        return _execute_scroll(x, y, direction, amount, dry_run, rng)

    elif t == ActionType.WAIT:
        # WAIT is a no-op at the action layer — the FSM handles timing
        return 0.0

    else:
        raise ActionError(
            ErrorCode.ACTION_TARGET_NOT_FOUND,
            f"Unknown action type: {t}",
            {"action_type": str(t)},
        )
