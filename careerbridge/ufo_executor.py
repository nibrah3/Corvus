# ufo_executor.py — Humanized UFO executor
#
# Subclasses UFOClient to intercept action commands and route them through
# ZeroClaw's pyautogui humanizer instead of UFO's native pywinauto executor.
#
# Data collection commands (screenshot, UIA tree, control listing) pass through
# to UFO's native execution unchanged — UFO still owns all perception.
#
# Runs inside UFO's Python process. Requires:
#   - E:\UFO-test in sys.path  (UFO imports)
#   - E:\cb-core   in sys.path  (ZeroClaw imports)
#   Both are set by ufo_launcher.py before this module is imported.

from __future__ import annotations

import logging
import random
import time
from typing import List, Optional

import pyautogui

from aip.messages import Command, Result, ResultStatus

from ufo.client.ufo_client import UFOClient
from ufo.client.mcp.local_servers.ui_mcp_server import UIServerState

from careerbridge.actions import _execute_click, _execute_type, _execute_scroll
from careerbridge.schema import BehaviorFingerprint
from careerbridge.types import MouseSpeed

logger = logging.getLogger(__name__)

pyautogui.PAUSE = 0
pyautogui.FAILSAFE = True

# Default profile used when no BehaviorFingerprint is supplied.
_DEFAULT_PROFILE = BehaviorFingerprint(
    typing_wpm=62,
    error_rate=0.03,
    mouse_speed=MouseSpeed.MEDIUM,
    pause_min_ms=80,
    pause_max_ms=350,
)

# UFO sends pywinauto-style key sequences. Map the ones that matter for
# browser/assessment automation to pyautogui equivalents.
# "press" → pyautogui.press(key)
# "hotkey" → pyautogui.hotkey(*keys)
_KEY_MAP: dict[str, tuple] = {
    "{ENTER}":          ("press", "enter"),
    "{TAB}":            ("press", "tab"),
    "{ESC}":            ("press", "escape"),
    "{BACKSPACE}":      ("press", "backspace"),
    "{DELETE}":         ("press", "delete"),
    "{HOME}":           ("press", "home"),
    "{END}":            ("press", "end"),
    "{PGUP}":           ("press", "pageup"),
    "{PGDN}":           ("press", "pagedown"),
    "{UP}":             ("press", "up"),
    "{DOWN}":           ("press", "down"),
    "{LEFT}":           ("press", "left"),
    "{RIGHT}":          ("press", "right"),
    "{VK_CONTROL}a":    ("hotkey", "ctrl", "a"),
    "{VK_CONTROL}c":    ("hotkey", "ctrl", "c"),
    "{VK_CONTROL}v":    ("hotkey", "ctrl", "v"),
    "{VK_CONTROL}z":    ("hotkey", "ctrl", "z"),
    "{VK_CONTROL}l":    ("hotkey", "ctrl", "l"),   # Chrome address bar
    "{VK_CONTROL}{END}": ("hotkey", "ctrl", "end"),
    "{VK_CONTROL}{HOME}": ("hotkey", "ctrl", "home"),
}

# Action tools that this executor intercepts.
_HUMANIZED_TOOLS = frozenset({
    "click_input",
    "click_on_coordinates",
    "set_edit_text",
    "wheel_mouse_input",
    "keyboard_input",
})


def _element_center(element_id: str) -> Optional[tuple[int, int]]:
    """Resolve a UFO annotation id to absolute screen center (x, y)."""
    ui_state = UIServerState()
    if not ui_state.control_dict:
        return None
    control = ui_state.control_dict.get(element_id)
    if control is None:
        return None
    try:
        rect = control.rectangle()
        cx = (rect.left + rect.right) // 2
        cy = (rect.top + rect.bottom) // 2
        return (cx, cy)
    except Exception:
        return None


def _window_focus() -> None:
    """Focus the active window via pywinauto set_focus (no DOM click)."""
    ui_state = UIServerState()
    if ui_state.selected_app_window:
        try:
            ui_state.selected_app_window.set_focus()
        except Exception:
            pass


class HumanizedUFOClient(UFOClient):
    """
    UFOClient subclass that replaces UFO's native pywinauto execution for
    action commands with ZeroClaw's pyautogui humanizer.

    UFO still owns all perception (screenshots, UIA tree, control listing).
    Only physical execution is swapped.
    """

    def __init__(
        self,
        profile: Optional[BehaviorFingerprint] = None,
        **kwargs,
    ) -> None:
        super().__init__(**kwargs)
        self._profile = profile or _DEFAULT_PROFILE
        self._rng = random.Random()

    async def execute_actions(self, commands: Optional[List[Command]]) -> List[Result]:
        if not commands:
            return []

        results: List[Result] = []
        native_passthrough: List[Command] = []

        for command in commands:
            call_id = command.call_id
            tool_name = command.tool_name or ""
            tool_type = command.tool_type or ""

            if not tool_name:
                results.append(Result(
                    status=ResultStatus.SUCCESS,
                    result="No action.",
                    error="",
                    call_id=call_id,
                ))
                continue

            # Data collection or unrecognised action → UFO native path
            if tool_type == "data_collection" or tool_name not in _HUMANIZED_TOOLS:
                native_passthrough.append(command)
                continue

            # Flush any pending native commands first (preserve ordering)
            if native_passthrough:
                native = await super().execute_actions(native_passthrough)
                results.extend(native)
                native_passthrough = []

            results.append(await self._humanize(call_id, tool_name, command.parameters or {}))

        # Flush remaining native commands
        if native_passthrough:
            native = await super().execute_actions(native_passthrough)
            results.extend(native)

        return results

    async def _humanize(self, call_id: str, tool_name: str, params: dict) -> Result:
        profile = self._profile
        rng = self._rng

        try:
            if tool_name == "click_input":
                return self._click_input(call_id, params, profile, rng)

            elif tool_name == "click_on_coordinates":
                return self._click_on_coordinates(call_id, params, profile, rng)

            elif tool_name == "set_edit_text":
                return self._set_edit_text(call_id, params, profile, rng)

            elif tool_name == "wheel_mouse_input":
                return self._wheel_mouse_input(call_id, params, profile, rng)

            elif tool_name == "keyboard_input":
                return self._keyboard_input(call_id, params)

            else:
                return Result(
                    status=ResultStatus.FAILURE,
                    error=f"No humanizer for tool: {tool_name}",
                    result=None,
                    call_id=call_id,
                )

        except Exception as exc:
            logger.error("Humanized %s failed: %s", tool_name, exc, exc_info=True)
            return Result(
                status=ResultStatus.FAILURE,
                error=str(exc),
                result=None,
                call_id=call_id,
            )

    # ── Individual action handlers ────────────────────────────────────────────

    def _click_input(
        self, call_id: str, params: dict, profile: BehaviorFingerprint, rng: random.Random
    ) -> Result:
        element_id = params.get("id", "")
        name = params.get("name", "")
        double = bool(params.get("double", False))

        center = _element_center(element_id)
        if center is None:
            return Result(
                status=ResultStatus.FAILURE,
                error=f"Cannot resolve element id={element_id!r} name={name!r}",
                result=None,
                call_id=call_id,
            )
        x, y = center
        _execute_click(x, y, profile, dry_run=False, rng=rng)
        if double:
            time.sleep(0.12)
            _execute_click(x, y, profile, dry_run=False, rng=rng)
        logger.info("click_input id=%s (%d,%d)", element_id, x, y)
        return Result(
            status=ResultStatus.SUCCESS,
            result=f"Clicked element {element_id!r} ({name}) at ({x},{y})",
            error=None,
            call_id=call_id,
        )

    def _click_on_coordinates(
        self, call_id: str, params: dict, profile: BehaviorFingerprint, rng: random.Random
    ) -> Result:
        ui_state = UIServerState()
        if not ui_state.selected_app_window:
            return Result(
                status=ResultStatus.FAILURE,
                error="No application window selected",
                result=None,
                call_id=call_id,
            )
        rect = ui_state.selected_app_window.rectangle()
        fx = float(params.get("x", 0.5))
        fy = float(params.get("y", 0.5))
        x = rect.left + int(fx * (rect.right  - rect.left))
        y = rect.top  + int(fy * (rect.bottom - rect.top))
        _execute_click(x, y, profile, dry_run=False, rng=rng)
        logger.info("click_on_coordinates (%.2f,%.2f) → (%d,%d)", fx, fy, x, y)
        return Result(
            status=ResultStatus.SUCCESS,
            result=f"Clicked fractional ({fx},{fy}) → screen ({x},{y})",
            error=None,
            call_id=call_id,
        )

    def _set_edit_text(
        self, call_id: str, params: dict, profile: BehaviorFingerprint, rng: random.Random
    ) -> Result:
        element_id = params.get("id", "")
        name = params.get("name", "")
        text = params.get("text", "")
        clear = bool(params.get("clear_current_text", False))

        center = _element_center(element_id)
        if center is None:
            return Result(
                status=ResultStatus.FAILURE,
                error=f"Cannot resolve element id={element_id!r} name={name!r}",
                result=None,
                call_id=call_id,
            )
        x, y = center

        if clear:
            _execute_click(x, y, profile, dry_run=False, rng=rng)
            pyautogui.hotkey("ctrl", "a", _pause=False)
            pyautogui.press("delete", _pause=False)
            time.sleep(0.05)

        # _execute_type clicks the field then types char-by-char
        _execute_type(x, y, text, profile, dry_run=False, rng=rng)
        logger.info("set_edit_text id=%s %d chars", element_id, len(text))
        return Result(
            status=ResultStatus.SUCCESS,
            result=f"Typed {len(text)} chars into element {element_id!r} ({name})",
            error=None,
            call_id=call_id,
        )

    def _wheel_mouse_input(
        self, call_id: str, params: dict, profile: BehaviorFingerprint, rng: random.Random
    ) -> Result:
        element_id = params.get("id", "")
        wheel_dist = int(params.get("wheel_dist", 0))

        if wheel_dist == 0:
            return Result(
                status=ResultStatus.SUCCESS,
                result="wheel_dist=0, nothing to scroll",
                error=None,
                call_id=call_id,
            )

        # Focus via pywinauto set_focus — NOT a DOM click.
        # A DOM click here would trap keyboard focus inside a scrollable div,
        # causing Page Down to scroll the div instead of the main page.
        _window_focus()

        center = _element_center(element_id)
        if center:
            x, y = center
        else:
            ui_state = UIServerState()
            if ui_state.selected_app_window:
                rect = ui_state.selected_app_window.rectangle()
                x = (rect.left + rect.right) // 2
                y = (rect.top  + rect.bottom) // 2
            else:
                x, y = pyautogui.position()

        direction = "down" if wheel_dist < 0 else "up"
        _execute_scroll(x, y, direction, abs(wheel_dist), dry_run=False, rng=rng)
        logger.info("wheel_mouse_input %s %d at (%d,%d)", direction, abs(wheel_dist), x, y)
        return Result(
            status=ResultStatus.SUCCESS,
            result=f"Scrolled {direction} {abs(wheel_dist)} notch(es) at ({x},{y})",
            error=None,
            call_id=call_id,
        )

    def _keyboard_input(self, call_id: str, params: dict) -> Result:
        keys = params.get("keys", "")
        mapped = _KEY_MAP.get(keys)

        if mapped:
            if mapped[0] == "hotkey":
                pyautogui.hotkey(*mapped[1:], _pause=False)
            else:
                pyautogui.press(mapped[1], _pause=False)
            logger.info("keyboard_input %r → %s", keys, mapped)
            return Result(
                status=ResultStatus.SUCCESS,
                result=f"Sent keys {keys!r}",
                error=None,
                call_id=call_id,
            )

        # Unknown key sequence — log and return success (UFO will observe result).
        logger.warning("keyboard_input: unmapped key sequence %r — skipped", keys)
        return Result(
            status=ResultStatus.SUCCESS,
            result=f"Skipped unmapped key sequence {keys!r}",
            error=None,
            call_id=call_id,
        )
