# actions.py — Action Layer (Phase 1)
# SCHEMA_VERSION: 2
#
# Single responsibility: OS-level mouse and keyboard execution.
#
# Delegates to humanizer_mcp._mouse / _keyboard / _scroll for all event delivery.
# Those modules use pyinterception (kernel-level, no LLKHF_INJECTED) with pynput
# fallback — no pyautogui in the execution path.
#
# Receives: Action + resolved BoundingBox + BehaviorFingerprint
# Returns:  ActionResult
#
# MUST NOT: read screen, call OCR, call LLM, look up UIElements.

from __future__ import annotations

import os
import random
import sys
import time
from dataclasses import dataclass
from typing import Optional

import pygetwindow as gw
from tenacity import retry, stop_after_attempt, wait_fixed, retry_if_exception_type

# Ensure cb-core is on path so humanizer_mcp sibling package is importable
_CB_DIR = os.path.normpath(os.path.join(os.path.dirname(__file__), ".."))
if _CB_DIR not in sys.path:
    sys.path.insert(0, _CB_DIR)

from humanizer_mcp._mouse    import click as _hum_click, move as _hum_move
from humanizer_mcp._keyboard import type_text as _hum_type, press_key as _hum_press
from humanizer_mcp._scroll   import scroll as _hum_scroll
from humanizer_mcp._profile  import BehaviorProfile

from .errors import ActionError, ErrorCode
from .schema import Action, BehaviorFingerprint, BoundingBox
from .types  import ActionType

_MAX_RETRIES: int = 3


# ── Result type ───────────────────────────────────────────────────────────────

@dataclass(frozen=True)
class ActionResult:
    success:       bool
    action_id:     str
    elapsed_ms:    float
    error_code:    Optional[ErrorCode] = None
    error_message: Optional[str]       = None


# ── BehaviorProfile bridge ────────────────────────────────────────────────────
# BehaviorFingerprint (schema.py) ↔ BehaviorProfile (humanizer_mcp/_profile.py)
# Both track the same parameters; we adapt one to the other here.

def _make_hum_profile(fingerprint: BehaviorFingerprint) -> BehaviorProfile:
    return BehaviorProfile(
        wpm=float(fingerprint.typing_wpm),
        error_rate=fingerprint.error_rate,
        mouse_speed=0.30,   # humanizer_mcp uses its own Fitts-law scaling
    )


# ── Core execution functions ──────────────────────────────────────────────────

def _execute_click(
    x: int,
    y: int,
    profile: BehaviorFingerprint,
    dry_run: bool,
    rng: random.Random,
) -> float:
    t0 = time.monotonic()
    if not dry_run:
        hum = _make_hum_profile(profile)
        _hum_click(x, y, button="left", double=False, profile=hum, rng=rng)
    return (time.monotonic() - t0) * 1000.0


def _execute_type(
    x: int,
    y: int,
    text: str,
    profile: BehaviorFingerprint,
    dry_run: bool,
    rng: random.Random,
) -> float:
    t0 = time.monotonic()
    if not dry_run:
        hum = _make_hum_profile(profile)
        # Click field first, then type
        _hum_click(x, y, button="left", profile=hum, rng=rng)
        time.sleep(rng.uniform(0.08, 0.18))  # brief focus settle
        _hum_type(text, profile=hum, rng=rng)
    return (time.monotonic() - t0) * 1000.0


def _execute_scroll(
    x: int,
    y: int,
    direction: str,
    amount: int,
    dry_run: bool,
    rng: random.Random,
) -> float:
    t0 = time.monotonic()
    if not dry_run:
        hum = BehaviorProfile.default()
        _hum_scroll(x, y, direction=direction, notches=amount, profile=hum, rng=rng)
    return (time.monotonic() - t0) * 1000.0


# ── Window focus ──────────────────────────────────────────────────────────────

def focus_window(title: str) -> None:
    matches = [w for w in gw.getAllWindows() if title.lower() in w.title.lower()]
    if not matches:
        raise ActionError(
            ErrorCode.CAPTURE_WINDOW_NOT_FOUND,
            f"No window found matching title: {title!r}",
            {"title": title},
        )
    try:
        matches[0].activate()
    except Exception:
        pass


# ── Public dispatch ───────────────────────────────────────────────────────────

def dispatch(
    action: Action,
    bbox: BoundingBox,
    profile: BehaviorFingerprint,
    dry_run: bool = False,
    _rng: Optional[random.Random] = None,
) -> ActionResult:
    rng = _rng or random.Random()
    x, y = bbox.center_x, bbox.center_y

    try:
        elapsed = _dispatch_inner(action, x, y, profile, dry_run, rng)
        return ActionResult(success=True, action_id=action.action_id, elapsed_ms=elapsed)
    except ActionError as e:
        return ActionResult(
            success=False, action_id=action.action_id, elapsed_ms=0.0,
            error_code=e.code, error_message=str(e),
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

    if t in (ActionType.CLICK, ActionType.FOCUS):
        return _execute_click(x, y, profile, dry_run, rng)
    elif t == ActionType.TYPE:
        return _execute_type(x, y, action.payload["text"], profile, dry_run, rng)
    elif t == ActionType.SCROLL:
        return _execute_scroll(
            x, y, action.payload["direction"], action.payload["amount"], dry_run, rng
        )
    elif t == ActionType.WAIT:
        return 0.0
    else:
        raise ActionError(
            ErrorCode.ACTION_TARGET_NOT_FOUND,
            f"Unknown action type: {t}",
            {"action_type": str(t)},
        )
