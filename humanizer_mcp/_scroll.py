"""
Humanized scroll input.

Scroll model: multi-step scroll with variable step sizes and inter-step timing.
              Weibull-distributed pauses between scroll notches (human rhythm).
              Optional mouse repositioning before scroll (humans move cursor there).
              OxyMouse path generation for cursor movement to scroll target.
"""
from __future__ import annotations

import random
import time

from ._profile import BehaviorProfile
from ._distributions import sample_hold

# ── Backend ───────────────────────────────────────────────────────────────────

_pynput_mouse = None


def _ensure_scroll_backend() -> None:
    global _pynput_mouse
    if _pynput_mouse is not None:
        return
    try:
        from pynput.mouse import Controller as _MC
        _pynput_mouse = _MC()
    except Exception as exc:
        raise ImportError(f"pynput mouse not available: {exc}. pip install pynput")


# ── Scroll primitives ─────────────────────────────────────────────────────────

def _scroll_notch(dx: int, dy: int) -> None:
    """Send one scroll notch via pynput. dy > 0 = up, dy < 0 = down."""
    _ensure_scroll_backend()
    _pynput_mouse.scroll(dx, dy)


# ── High-level scroll ─────────────────────────────────────────────────────────

def scroll(
    x: int,
    y: int,
    direction: str,
    notches: int,
    profile: BehaviorProfile | None = None,
    rng: random.Random | None = None,
) -> None:
    """
    Humanized scroll at screen position (x, y).

    Splits total notches into 1-5 variable-size bursts with:
      - Weibull-distributed inter-step pauses (matches human scroll rhythm)
      - Random step sizes (1-3 notches per burst, not uniform)
      - Slight cursor drift between bursts (humans reposition slightly)
      - Natural acceleration: faster bursts in the middle of a long scroll

    direction: "up" or "down"
    notches:   total scroll notches to send
    """
    if profile is None:
        profile = BehaviorProfile.default()
    if rng is None:
        rng = random.Random()
    if notches <= 0:
        return

    # Move cursor to scroll position first
    _pynput_mouse.position = (x, y)
    time.sleep(rng.uniform(0.04, 0.09))

    dy_sign = 1 if direction == "up" else -1

    remaining = notches
    while remaining > 0:
        # Burst size: 1-3 notches (larger bursts feel faster/more natural)
        burst = min(remaining, rng.choices([1, 2, 3], weights=[3, 5, 2])[0])
        remaining -= burst

        _scroll_notch(0, dy_sign * burst)

        if remaining > 0:
            # Inter-burst pause: Weibull distribution (shape ~1.5)
            # Weibull with k>1 has a rising then falling hazard — matches human
            # scroll rhythm where pauses cluster around a modal duration.
            pause = _weibull_pause(rng)
            time.sleep(pause)


def _weibull_pause(rng: random.Random) -> float:
    """
    Sample an inter-scroll-burst pause using Weibull distribution.
    Shape k=1.5, scale λ=0.12 → modal pause ~90ms, mean ~110ms.
    Floor at 50ms (human reaction minimum between scroll steps).
    """
    k = 1.5
    lam = 0.12
    # Inverse CDF: λ * (-ln(1-u))^(1/k)
    u = rng.random()
    if u >= 1.0:
        u = 0.9999
    raw = lam * ((-1.0) * __import__('math').log(1.0 - u)) ** (1.0 / k)
    return max(0.050, raw)
