"""
Humanizer MCP server.

Exposes five tools to Claude Code:
  humanized_click   — move + hover + mouseDown + hold + mouseUp
  humanized_type    — character-by-character with ex-Gaussian IKI + bigrams + typos
  humanized_scroll  — multi-burst scroll with Weibull inter-step pauses
  humanized_drag    — click-and-drag between two screen positions
  press_key         — named key (enter, tab, escape, …) with hold duration
  hotkey            — key combination (ctrl+a, ctrl+v, …)

All tools accept an optional profile_seed integer to produce deterministic
per-session variation (same seed → same timing fingerprint across a session).
"""
from __future__ import annotations

import random
import threading
import time
from typing import Optional

from _minmcp import MinMCP

from ._profile import BehaviorProfile
from ._mouse import click as _mouse_click, drag as _mouse_drag, move as _mouse_move
from ._keyboard import type_text as _kb_type, press_key as _kb_press, hotkey as _kb_hotkey
from ._scroll import scroll as _scroll

mcp = MinMCP("humanizer")

# ── Session profile cache ─────────────────────────────────────────────────────
# Keyed by profile_seed so Claude Code can pass the same seed each turn and
# get consistent timing variation within one session.

_profile_cache: dict[int, BehaviorProfile] = {}
_rng_cache: dict[int, random.Random] = {}

# ── Async typing state ────────────────────────────────────────────────────────
# Characters below this threshold are typed synchronously (fast, no thread).
# Characters above are typed in a background thread so the MCP tool call
# returns before the client times out. Call wait_for_typing() afterward.
_ASYNC_THRESHOLD = 200

_typing_lock  = threading.Lock()      # only one typing job at a time
_typing_done  = threading.Event()     # set when background typing finishes
_typing_done.set()                    # initially "nothing is typing"
_typing_error: list[str] = []        # stores error message if typing thread crashes


def _get_session(seed: Optional[int]) -> tuple[BehaviorProfile, random.Random]:
    if seed is None:
        return BehaviorProfile.default(), random.Random()
    if seed not in _profile_cache:
        rng = random.Random(seed)
        _profile_cache[seed] = BehaviorProfile.default()
        _rng_cache[seed] = rng
    return _profile_cache[seed], _rng_cache[seed]


# ── Tools ─────────────────────────────────────────────────────────────────────

@mcp.tool()
def humanized_click(
    x: int,
    y: int,
    button: str = "left",
    double: bool = False,
    profile_seed: Optional[int] = None,
) -> str:
    """
    Move cursor to (x, y) via WindMouse path and click with realistic timing.

    Args:
        x: Screen x coordinate (absolute pixels).
        y: Screen y coordinate (absolute pixels).
        button: "left" or "right".
        double: True to double-click.
        profile_seed: Integer seed for reproducible per-session timing variation.
                      Pass the same seed for all calls in one job session.
    """
    profile, rng = _get_session(profile_seed)
    _mouse_click(x, y, button=button, double=double, profile=profile, rng=rng)
    action = "double-clicked" if double else "clicked"
    return f"{action} ({x}, {y}) with {button} button"


@mcp.tool()
def humanized_type(
    text: str,
    profile_seed: Optional[int] = None,
) -> str:
    """
    Type text character-by-character with human timing.

    Includes: ex-Gaussian IKI, bigram acceleration, fatigue slowdown,
    QWERTY-adjacent typo+backspace correction, inter-word and post-punctuation
    pauses, realistic key hold duration.

    Cursor must already be in the target field before calling.

    SHORT text (<= 200 chars): typed synchronously — tool blocks until done.
    LONG text  (>  200 chars): typed in a background thread — tool returns
    immediately with an ETA. Call wait_for_typing() before your next
    keyboard/mouse action to ensure typing has finished.

    Args:
        text: The string to type.
        profile_seed: Integer seed for reproducible per-session timing.
    """
    global _typing_error
    profile, rng = _get_session(profile_seed)
    n = len(text)

    if n <= _ASYNC_THRESHOLD:
        # Short text: type synchronously — safe within timeout
        _kb_type(text, profile=profile, rng=rng)
        return f"typed {n} characters"

    # Long text: background thread so we respond before the client times out.
    # Estimate wall-clock time: average effective IKI ~175ms (includes spaces,
    # punctuation pauses, typo corrections) plus 60ms hold per character.
    eta_s = n * 0.175

    if not _typing_lock.acquire(blocking=False):
        return f"error: another typing job is still running — call wait_for_typing() first"

    _typing_done.clear()
    _typing_error.clear()

    def _bg_type():
        try:
            _kb_type(text, profile=profile, rng=rng)
        except Exception as exc:
            _typing_error.append(str(exc))
        finally:
            _typing_done.set()
            _typing_lock.release()

    t = threading.Thread(target=_bg_type, daemon=True, name="humanizer-type")
    t.start()

    return f"typing_started: {n} chars | ETA {eta_s:.0f}s | call wait_for_typing() before next action"


@mcp.tool()
def wait_for_typing(timeout_s: float = 120.0) -> str:
    """
    Block until the background humanized_type job finishes (or timeout elapses).

    Always call this after a long humanized_type before clicking Submit,
    navigating, or typing into another field.

    Args:
        timeout_s: Maximum seconds to wait (default 120).
                   Set higher for very long paragraphs.
    Returns:
        "done"    — typing completed successfully.
        "timeout" — typing still in progress after timeout_s seconds.
        "error"   — the typing thread crashed (error message included).
        "idle"    — no background typing was running (safe to proceed).
    """
    if _typing_done.is_set():
        return "idle"

    finished = _typing_done.wait(timeout=timeout_s)
    if not finished:
        return f"timeout: typing still running after {timeout_s:.0f}s"
    if _typing_error:
        return f"error: {_typing_error[0]}"
    return "done"


@mcp.tool()
def humanized_scroll(
    x: int,
    y: int,
    direction: str,
    notches: int = 3,
    profile_seed: Optional[int] = None,
) -> str:
    """
    Scroll at screen position (x, y) with human-like burst timing.

    Args:
        x: Screen x coordinate to position cursor before scrolling.
        y: Screen y coordinate.
        direction: "up" or "down".
        notches: Total scroll notches.
        profile_seed: Integer seed for reproducible per-session timing.
    """
    profile, rng = _get_session(profile_seed)
    _scroll(x, y, direction=direction, notches=notches, profile=profile, rng=rng)
    return f"scrolled {direction} {notches} notch(es) at ({x}, {y})"


@mcp.tool()
def humanized_drag(
    x0: int,
    y0: int,
    x1: int,
    y1: int,
    profile_seed: Optional[int] = None,
) -> str:
    """
    Click-and-drag from (x0, y0) to (x1, y1) with WindMouse path.

    Args:
        x0: Drag start x.
        y0: Drag start y.
        x1: Drag end x.
        y1: Drag end y.
        profile_seed: Integer seed for reproducible per-session timing.
    """
    profile, rng = _get_session(profile_seed)
    _mouse_drag(x0, y0, x1, y1, profile=profile, rng=rng)
    return f"dragged ({x0},{y0}) → ({x1},{y1})"


@mcp.tool()
def humanized_press_key(
    key_name: str,
    profile_seed: Optional[int] = None,
) -> str:
    """
    Press a named key with realistic hold duration.

    Supported keys: enter, tab, escape, backspace, delete, home, end,
                    pageup, pagedown, up, down, left, right, f5.

    Args:
        key_name: Key name string (case-insensitive).
        profile_seed: Integer seed for reproducible per-session timing.
    """
    profile, rng = _get_session(profile_seed)
    _kb_press(key_name, profile=profile, rng=rng)
    return f"pressed {key_name}"


@mcp.tool()
def humanized_hotkey(
    keys: list[str],
    profile_seed: Optional[int] = None,
) -> str:
    """
    Press a key combination with natural inter-key delays.

    Keys are pressed sequentially (not simultaneously) with ~30ms inter-key
    delays, then released in reverse order — matches real human hotkey behavior.

    Args:
        keys: Ordered list of key names, e.g. ["ctrl", "a"] or ["ctrl", "shift", "t"].
              Modifier names: ctrl, shift, alt, win.
        profile_seed: Integer seed for reproducible per-session timing.
    """
    profile, rng = _get_session(profile_seed)
    _kb_hotkey(*keys, profile=profile, rng=rng)
    return f"hotkey {'+'.join(keys)}"


@mcp.tool()
def humanized_move(
    x: int,
    y: int,
    profile_seed: Optional[int] = None,
) -> str:
    """
    Move cursor to (x, y) via WindMouse path without clicking.
    Useful for hover effects or pre-positioning before a timed action.

    Args:
        x: Target x coordinate.
        y: Target y coordinate.
        profile_seed: Integer seed for reproducible per-session timing.
    """
    profile, rng = _get_session(profile_seed)
    _mouse_move(x, y, profile=profile, rng=rng)
    return f"moved cursor to ({x}, {y})"


# ── Entry point ───────────────────────────────────────────────────────────────

if __name__ == "__main__":
    mcp.run()
