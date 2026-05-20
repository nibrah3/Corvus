"""
Mouse movement, clicking, and dragging.

Path generation: windmouse library (physics-based, non-uniform velocity)
                 + ease-in-out easing on t-parameter
                 + Gaussian tremor during pauses
OS delivery:     pyinterception (kernel driver, no LLKHF_INJECTED) if available,
                 falls back to pynput (SendInput, relative coordinates)
Click model:     mouseDown + ex-Gaussian hold + mouseUp (not atomic pyautogui.click)
Overshoot:       ~30% chance on moves >300px — corrective sub-movement after arrival
"""
from __future__ import annotations

import math
import random
import time
from typing import Tuple

from ._profile import BehaviorProfile
from ._distributions import sample_pre_click, sample_hold, sample_mouse_tremor

# ── Backend selection ─────────────────────────────────────────────────────────
# Try pyinterception (kernel driver — removes LLKHF_INJECTED flag).
# Fall back to pynput (SendInput — still acceptable for browser-based platforms).

_backend = "uninitialized"
_pynput_mouse = None
_Button = None
_icp = None
_icp_mouse = None


def _ensure_backend() -> None:
    global _backend, _pynput_mouse, _Button, _icp, _icp_mouse
    if _backend != "uninitialized":
        return
    try:
        import interception as _icp_mod
        _icp = _icp_mod.Interception()
        _icp_mouse = _icp_mod.MouseStroke()
        _backend = "interception"
        return
    except Exception:
        pass
    try:
        from pynput.mouse import Controller as _MC, Button as _Btn
        _pynput_mouse = _MC()
        _Button = _Btn
        _backend = "pynput"
        return
    except Exception:
        pass
    _backend = "unavailable"
    raise ImportError("No mouse backend available. Install pynput: pip install pynput")


# ── WindMouse path generator ──────────────────────────────────────────────────

try:
    from windmouse import generate_wind_mouse_input as _windmouse_raw
    _HAS_WINDMOUSE = True
except ImportError:
    _HAS_WINDMOUSE = False


def _windmouse_path(
    x0: int, y0: int, x1: int, y1: int,
    gravity: float = 9.0,
    wind: float = 3.0,
) -> list[Tuple[int, int]]:
    """
    Generate a WindMouse path from (x0,y0) to (x1,y1).
    Falls back to simple bezier if windmouse not installed.
    """
    if _HAS_WINDMOUSE:
        try:
            raw = _windmouse_raw(x0, y0, x1, y1, G_0=gravity, W_0=wind,
                                  M_0=15, D_0=12)
            return [(int(x), int(y)) for x, y in raw]
        except Exception:
            pass
    # Fallback: cubic bezier with randomised control points
    return _bezier_path(x0, y0, x1, y1)


def _bezier_path(
    x0: int, y0: int, x1: int, y1: int,
    n_points: int = 50,
) -> list[Tuple[int, int]]:
    """Cubic bezier fallback with ease-in-out t-sampling."""
    rng = random.Random()
    dist = math.hypot(x1 - x0, y1 - y0)
    jitter = min(80, max(10, int(dist * 0.18)))

    cx1 = x0 + rng.randint(10, jitter) * rng.choice([-1, 1])
    cy1 = y0 + rng.randint(5, jitter) * rng.choice([-1, 1])
    cx2 = x1 + rng.randint(10, jitter) * rng.choice([-1, 1])
    cy2 = y1 + rng.randint(5, jitter) * rng.choice([-1, 1])

    def _ease(t: float) -> float:
        # Ease-in-out cubic: slow → fast → slow
        return t * t * (3 - 2 * t)

    def _bezier(t: float) -> Tuple[int, int]:
        u = 1 - t
        x = u**3*x0 + 3*u**2*t*cx1 + 3*u*t**2*cx2 + t**3*x1
        y = u**3*y0 + 3*u**2*t*cy1 + 3*u*t**2*cy2 + t**3*y1
        return (int(x), int(y))

    return [_bezier(_ease(i / n_points)) for i in range(n_points + 1)]


# ── OS-level move primitives ──────────────────────────────────────────────────

def _move_to_absolute(x: int, y: int) -> None:
    """Move cursor to absolute screen position (x, y)."""
    _ensure_backend()
    if _backend == "interception":
        # Interception uses relative movement — compute delta from current position
        cx, cy = _get_position()
        _icp_mouse.x = x - cx
        _icp_mouse.y = y - cy
        _icp_mouse.flags = interception.MouseFlag.MOVE_RELATIVE
        _icp.send(_icp.get_foreground_device(interception.DeviceType.MOUSE), _icp_mouse)
    elif _backend == "pynput":
        _pynput_mouse.position = (x, y)


def _move_relative(dx: int, dy: int) -> None:
    """Move cursor by (dx, dy) pixels — matches real HID mouse reporting."""
    _ensure_backend()
    if _backend == "interception":
        _icp_mouse.x = dx
        _icp_mouse.y = dy
        _icp_mouse.flags = interception.MouseFlag.MOVE_RELATIVE
        _icp.send(_icp.get_foreground_device(interception.DeviceType.MOUSE), _icp_mouse)
    elif _backend == "pynput":
        _pynput_mouse.move(dx, dy)


def _get_position() -> Tuple[int, int]:
    _ensure_backend()
    if _backend == "pynput":
        pos = _pynput_mouse.position
        return (int(pos[0]), int(pos[1]))
    # For interception, read via win32 as fallback
    try:
        import ctypes
        pt = ctypes.wintypes.POINT()
        ctypes.windll.user32.GetCursorPos(ctypes.byref(pt))
        return (pt.x, pt.y)
    except Exception:
        return (0, 0)


def _mouse_down(button: str = "left") -> None:
    _ensure_backend()
    if _backend == "pynput":
        btn = _Button.left if button == "left" else _Button.right
        _pynput_mouse.press(btn)
    elif _backend == "interception":
        _icp_mouse.state = (
            interception.MouseState.LEFT_BUTTON_DOWN
            if button == "left"
            else interception.MouseState.RIGHT_BUTTON_DOWN
        )
        _icp_mouse.flags = interception.MouseFlag.MOVE_NOCOALESCE
        _icp.send(_icp.get_foreground_device(interception.DeviceType.MOUSE), _icp_mouse)


def _mouse_up(button: str = "left") -> None:
    _ensure_backend()
    if _backend == "pynput":
        btn = _Button.left if button == "left" else _Button.right
        _pynput_mouse.release(btn)
    elif _backend == "interception":
        _icp_mouse.state = (
            interception.MouseState.LEFT_BUTTON_UP
            if button == "left"
            else interception.MouseState.RIGHT_BUTTON_UP
        )
        _icp_mouse.flags = interception.MouseFlag.MOVE_NOCOALESCE
        _icp.send(_icp.get_foreground_device(interception.DeviceType.MOUSE), _icp_mouse)


# ── High-level actions ────────────────────────────────────────────────────────

def move(
    x: int, y: int,
    profile: BehaviorProfile,
    rng: random.Random,
) -> None:
    """
    Move cursor from current position to (x, y) via WindMouse path.
    Event rate targets ~250 Hz (4ms between moves) with tremor overlay.
    Duration scales with distance per Fitts's Law approximation.
    """
    cx, cy = _get_position()
    dist = math.hypot(x - cx, y - cy)

    if dist < 2:
        return  # already there

    # Fitts's Law-inspired duration: base_speed * sqrt(dist/400)
    duration = profile.mouse_speed * math.sqrt(dist / 400.0)
    duration = max(0.08, duration + rng.gauss(0, 0.02))

    path = _windmouse_path(cx, cy, x, y)
    n = len(path)
    if n == 0:
        return

    step_delay = duration / n
    tremor = sample_mouse_tremor(n, amplitude_px=1.2)

    prev_x, prev_y = cx, cy
    for i, (px, py) in enumerate(path):
        tx = px + int(tremor[i, 0])
        ty = py + int(tremor[i, 1])
        dx = tx - prev_x
        dy = ty - prev_y
        if dx != 0 or dy != 0:
            _move_relative(dx, dy)
        prev_x, prev_y = tx, ty

        # Sleep targeting ~250 Hz; use perf_counter for precision
        deadline = time.perf_counter() + step_delay
        while time.perf_counter() < deadline:
            pass  # busy-wait for sub-ms precision

    # Ensure exact arrival
    fx, fy = _get_position()
    if fx != x or fy != y:
        _move_relative(x - fx, y - fy)


def _overshoot_correct(
    x: int, y: int,
    dist: float,
    profile: BehaviorProfile,
    rng: random.Random,
) -> None:
    """
    Simulate ballistic overshoot + correction: move 3-8px past target,
    pause briefly, then correct. Triggered on long moves (dist > 300px).
    """
    if dist < 300 or rng.random() > profile.overshoot_prob:
        return

    angle = rng.uniform(0, 2 * math.pi)
    over_px = rng.randint(3, 8)
    ox = x + int(over_px * math.cos(angle))
    oy = y + int(over_px * math.sin(angle))

    _move_relative(ox - x, oy - y)
    time.sleep(rng.uniform(0.04, 0.12))
    _move_relative(x - ox, y - oy)


def click(
    x: int, y: int,
    button: str = "left",
    double: bool = False,
    profile: BehaviorProfile | None = None,
    rng: random.Random | None = None,
) -> None:
    """
    Full humanized click: move → hover pause → mouseDown → hold → mouseUp.
    Double-click repeats with realistic inter-click interval.
    """
    if profile is None:
        profile = BehaviorProfile.default()
    if rng is None:
        rng = random.Random()

    cx, cy = _get_position()
    dist = math.hypot(x - cx, y - cy)

    move(x, y, profile, rng)
    _overshoot_correct(x, y, dist, profile, rng)

    # Pre-click hover dwell
    hover = sample_pre_click(profile.pre_click_k, profile.pre_click_scale)
    time.sleep(hover)

    # Add tiny pre-click tremor drift
    drift_x = rng.randint(-1, 1)
    drift_y = rng.randint(-1, 1)
    if drift_x or drift_y:
        _move_relative(drift_x, drift_y)
        _move_relative(-drift_x, -drift_y)

    def _single_click() -> None:
        _mouse_down(button)
        hold = sample_hold(profile.hold_k, profile.hold_scale)
        time.sleep(hold)
        _mouse_up(button)

    _single_click()

    if double:
        # Inter-click interval: 80-180ms (lognormal-like)
        ici = max(0.08, min(0.18, rng.gauss(0.12, 0.025)))
        time.sleep(ici)
        _single_click()

    # Post-click micro-drift (humans don't freeze after clicking)
    time.sleep(rng.uniform(0.03, 0.08))


def drag(
    x0: int, y0: int, x1: int, y1: int,
    profile: BehaviorProfile | None = None,
    rng: random.Random | None = None,
) -> None:
    """Click-and-drag from (x0,y0) to (x1,y1)."""
    if profile is None:
        profile = BehaviorProfile.default()
    if rng is None:
        rng = random.Random()

    move(x0, y0, profile, rng)
    time.sleep(sample_pre_click(profile.pre_click_k, profile.pre_click_scale))
    _mouse_down("left")
    time.sleep(rng.uniform(0.04, 0.10))
    move(x1, y1, profile, rng)
    time.sleep(rng.uniform(0.03, 0.08))
    _mouse_up("left")
