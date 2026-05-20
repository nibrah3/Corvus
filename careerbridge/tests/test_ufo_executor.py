# test_ufo_executor.py — Real tests for HumanizedUFOClient
#
# Tests cover:
#   - _element_center: correct resolution, missing id, empty dict
#   - execute_actions routing: humanized vs passthrough
#   - click_input: correct coords, double-click, unknown element
#   - set_edit_text: typing, clear=True flow
#   - wheel_mouse_input: direction mapping, zero-dist no-op, window fallback
#   - keyboard_input: mapped keys, unmapped keys
#   - Ordering: native passthrough flushes before humanized commands
#
# Requires E:\UFO-test on sys.path (UFO must be installed there).
# Skip gracefully if UFO is not available.

from __future__ import annotations

import asyncio
import os
import sys
import types
from typing import Optional
from unittest.mock import AsyncMock, MagicMock, call, patch

import pytest

# ── Environment setup ─────────────────────────────────────────────────────────
_UFO_ROOT = r"E:\UFO-test"
_ZC_ROOT  = r"E:\cb-core"

for _p in (_UFO_ROOT, _ZC_ROOT):
    if _p not in sys.path:
        sys.path.insert(0, _p)

try:
    from aip.messages import Command, Result, ResultStatus
    _HAS_UFO = True
except ImportError:
    _HAS_UFO = False

pytestmark = pytest.mark.skipif(
    not _HAS_UFO,
    reason="UFO not available at E:\\UFO-test — install UFO dependencies first",
)

if _HAS_UFO:
    from careerbridge.ufo_executor import (
        HumanizedUFOClient,
        _element_center,
        _window_focus,
        _KEY_MAP,
        _HUMANIZED_TOOLS,
    )
    from careerbridge.schema import BehaviorFingerprint
    from careerbridge.types import MouseSpeed


# ── Helpers ───────────────────────────────────────────────────────────────────

def _profile() -> BehaviorFingerprint:
    return BehaviorFingerprint(
        typing_wpm=60,
        error_rate=0.0,
        mouse_speed=MouseSpeed.FAST,
        pause_min_ms=0,
        pause_max_ms=1,
    )


def _cmd(tool_name: str, tool_type: str = "action", params: dict = None, call_id: str = "c1") -> Command:
    return Command(tool_name=tool_name, tool_type=tool_type, parameters=params or {}, call_id=call_id)


def _mock_control(left=100, top=200, right=180, bottom=220) -> MagicMock:
    ctrl = MagicMock()
    rect = MagicMock()
    rect.left, rect.top, rect.right, rect.bottom = left, top, right, bottom
    ctrl.rectangle.return_value = rect
    return ctrl


def _make_client(profile=None) -> HumanizedUFOClient:
    """Instantiate HumanizedUFOClient with fully mocked UFO dependencies."""
    mock_mcp = MagicMock()
    mock_computer = MagicMock()
    return HumanizedUFOClient(
        profile=profile or _profile(),
        mcp_server_manager=mock_mcp,
        computer_manager=mock_computer,
        client_id="test_001",
        platform="windows",
    )


def run(coro):
    return asyncio.get_event_loop().run_until_complete(coro)


# ── _element_center ───────────────────────────────────────────────────────────

class TestElementCenter:

    def test_resolves_center_correctly(self):
        ctrl = _mock_control(left=100, top=200, right=180, bottom=220)
        mock_state = MagicMock()
        mock_state.control_dict = {"7": ctrl}
        with patch("careerbridge.ufo_executor.UIServerState", return_value=mock_state):
            result = _element_center("7")
        assert result == (140, 210)   # (100+180)//2=140, (200+220)//2=210

    def test_returns_none_when_id_missing(self):
        mock_state = MagicMock()
        mock_state.control_dict = {"7": _mock_control()}
        with patch("careerbridge.ufo_executor.UIServerState", return_value=mock_state):
            result = _element_center("99")
        assert result is None

    def test_returns_none_when_control_dict_empty(self):
        mock_state = MagicMock()
        mock_state.control_dict = {}
        with patch("careerbridge.ufo_executor.UIServerState", return_value=mock_state):
            result = _element_center("1")
        assert result is None

    def test_returns_none_when_control_dict_is_none(self):
        mock_state = MagicMock()
        mock_state.control_dict = None
        with patch("careerbridge.ufo_executor.UIServerState", return_value=mock_state):
            result = _element_center("1")
        assert result is None

    def test_returns_none_on_rectangle_exception(self):
        ctrl = MagicMock()
        ctrl.rectangle.side_effect = RuntimeError("UIA error")
        mock_state = MagicMock()
        mock_state.control_dict = {"1": ctrl}
        with patch("careerbridge.ufo_executor.UIServerState", return_value=mock_state):
            result = _element_center("1")
        assert result is None


# ── Routing ───────────────────────────────────────────────────────────────────

class TestRouting:

    def test_empty_commands_returns_empty(self):
        client = _make_client()
        result = run(client.execute_actions([]))
        assert result == []

    def test_none_commands_returns_empty(self):
        client = _make_client()
        result = run(client.execute_actions(None))
        assert result == []

    def test_no_tool_name_returns_success(self):
        client = _make_client()
        cmd = Command(tool_name="", tool_type="action", parameters={}, call_id="c0")
        result = run(client.execute_actions([cmd]))
        assert len(result) == 1
        assert result[0].status == ResultStatus.SUCCESS

    def test_data_collection_passes_through(self):
        client = _make_client()
        cmd = _cmd("get_desktop_app_info", tool_type="data_collection")
        native_result = [Result(status=ResultStatus.SUCCESS, result="ok", error=None, call_id="c1")]
        with patch.object(client.__class__.__bases__[0], "execute_actions", new=AsyncMock(return_value=native_result)):
            result = run(client.execute_actions([cmd]))
        assert result == native_result

    def test_unknown_action_passes_through(self):
        client = _make_client()
        cmd = _cmd("some_unknown_tool", tool_type="action")
        native_result = [Result(status=ResultStatus.SUCCESS, result="ok", error=None, call_id="c1")]
        with patch.object(client.__class__.__bases__[0], "execute_actions", new=AsyncMock(return_value=native_result)):
            result = run(client.execute_actions([cmd]))
        assert result == native_result

    def test_native_flush_before_humanized(self):
        """Native commands before a humanized command must flush first (order preserved)."""
        client = _make_client()
        call_order = []

        native_result = [Result(status=ResultStatus.SUCCESS, result="native", error=None, call_id="c1")]

        async def mock_super_execute(_self, commands):
            call_order.append("native")
            return native_result

        ctrl = _mock_control(100, 200, 180, 220)
        mock_state = MagicMock()
        mock_state.control_dict = {"7": ctrl}
        mock_state.selected_app_window = None

        with patch.object(client.__class__.__bases__[0], "execute_actions", new=mock_super_execute), \
             patch("careerbridge.ufo_executor.UIServerState", return_value=mock_state), \
             patch("careerbridge.ufo_executor._execute_click") as mock_click:
            mock_click.side_effect = lambda *a, **k: call_order.append("click")

            cmds = [
                _cmd("get_desktop_app_info", "data_collection", call_id="c1"),
                _cmd("click_input", params={"id": "7", "name": "OK"}, call_id="c2"),
            ]
            run(client.execute_actions(cmds))

        assert call_order[0] == "native"   # native flushed first
        assert call_order[1] == "click"    # then humanized


# ── click_input ───────────────────────────────────────────────────────────────

class TestClickInput:

    def _setup_state(self, element_id="7", left=100, top=200, right=180, bottom=220):
        ctrl = _mock_control(left, top, right, bottom)
        mock_state = MagicMock()
        mock_state.control_dict = {element_id: ctrl}
        return mock_state

    def test_click_calls_execute_click_with_center(self):
        client = _make_client()
        mock_state = self._setup_state("7", 100, 200, 180, 220)
        with patch("careerbridge.ufo_executor.UIServerState", return_value=mock_state), \
             patch("careerbridge.ufo_executor._execute_click") as mock_click:
            cmd = _cmd("click_input", params={"id": "7", "name": "Submit"})
            result = run(client.execute_actions([cmd]))

        mock_click.assert_called_once()
        args = mock_click.call_args[0]
        assert args[0] == 140   # x center
        assert args[1] == 210   # y center
        assert result[0].status == ResultStatus.SUCCESS

    def test_double_click_calls_execute_click_twice(self):
        client = _make_client()
        mock_state = self._setup_state("3")
        with patch("careerbridge.ufo_executor.UIServerState", return_value=mock_state), \
             patch("careerbridge.ufo_executor._execute_click") as mock_click, \
             patch("careerbridge.ufo_executor.time") as mock_time:
            cmd = _cmd("click_input", params={"id": "3", "name": "Item", "double": True})
            result = run(client.execute_actions([cmd]))

        assert mock_click.call_count == 2
        assert result[0].status == ResultStatus.SUCCESS

    def test_unknown_element_returns_failure(self):
        client = _make_client()
        mock_state = MagicMock()
        mock_state.control_dict = {}
        with patch("careerbridge.ufo_executor.UIServerState", return_value=mock_state), \
             patch("careerbridge.ufo_executor._execute_click") as mock_click:
            cmd = _cmd("click_input", params={"id": "99", "name": "Ghost"})
            result = run(client.execute_actions([cmd]))

        mock_click.assert_not_called()
        assert result[0].status == ResultStatus.FAILURE
        assert "99" in result[0].error

    def test_right_click_passes_correct_coords(self):
        client = _make_client()
        mock_state = self._setup_state("2", 50, 60, 150, 80)
        with patch("careerbridge.ufo_executor.UIServerState", return_value=mock_state), \
             patch("careerbridge.ufo_executor._execute_click") as mock_click:
            cmd = _cmd("click_input", params={"id": "2", "name": "Menu", "button": "right"})
            run(client.execute_actions([cmd]))

        args = mock_click.call_args[0]
        assert args[0] == 100   # (50+150)//2
        assert args[1] == 70    # (60+80)//2


# ── set_edit_text ─────────────────────────────────────────────────────────────

class TestSetEditText:

    def test_types_text_into_element(self):
        client = _make_client()
        ctrl = _mock_control(300, 400, 500, 420)
        mock_state = MagicMock()
        mock_state.control_dict = {"8": ctrl}
        with patch("careerbridge.ufo_executor.UIServerState", return_value=mock_state), \
             patch("careerbridge.ufo_executor._execute_type") as mock_type:
            cmd = _cmd("set_edit_text", params={"id": "8", "name": "Address", "text": "hello"})
            result = run(client.execute_actions([cmd]))

        mock_type.assert_called_once()
        call_args = mock_type.call_args[0]
        assert call_args[0] == 400   # x center
        assert call_args[1] == 410   # y center
        assert call_args[2] == "hello"
        assert result[0].status == ResultStatus.SUCCESS

    def test_clear_true_calls_ctrl_a_delete_first(self):
        client = _make_client()
        ctrl = _mock_control(0, 0, 100, 20)
        mock_state = MagicMock()
        mock_state.control_dict = {"1": ctrl}
        call_order = []
        with patch("careerbridge.ufo_executor.UIServerState", return_value=mock_state), \
             patch("careerbridge.ufo_executor._execute_click", side_effect=lambda *a, **k: call_order.append("click")), \
             patch("careerbridge.ufo_executor._execute_type",  side_effect=lambda *a, **k: call_order.append("type")), \
             patch("careerbridge.ufo_executor.pyautogui") as mock_pa:
            cmd = _cmd("set_edit_text", params={"id": "1", "name": "Field", "text": "new", "clear_current_text": True})
            result = run(client.execute_actions([cmd]))

        mock_pa.hotkey.assert_called_with("ctrl", "a", _pause=False)
        mock_pa.press.assert_called_with("delete", _pause=False)
        assert call_order == ["click", "type"]
        assert result[0].status == ResultStatus.SUCCESS

    def test_clear_false_does_not_call_ctrl_a(self):
        client = _make_client()
        ctrl = _mock_control()
        mock_state = MagicMock()
        mock_state.control_dict = {"1": ctrl}
        with patch("careerbridge.ufo_executor.UIServerState", return_value=mock_state), \
             patch("careerbridge.ufo_executor._execute_type"), \
             patch("careerbridge.ufo_executor.pyautogui") as mock_pa:
            cmd = _cmd("set_edit_text", params={"id": "1", "name": "f", "text": "x", "clear_current_text": False})
            run(client.execute_actions([cmd]))

        mock_pa.hotkey.assert_not_called()

    def test_unknown_element_returns_failure(self):
        client = _make_client()
        mock_state = MagicMock()
        mock_state.control_dict = {}
        with patch("careerbridge.ufo_executor.UIServerState", return_value=mock_state), \
             patch("careerbridge.ufo_executor._execute_type") as mock_type:
            cmd = _cmd("set_edit_text", params={"id": "99", "name": "x", "text": "y"})
            result = run(client.execute_actions([cmd]))

        mock_type.assert_not_called()
        assert result[0].status == ResultStatus.FAILURE


# ── wheel_mouse_input ─────────────────────────────────────────────────────────

class TestWheelMouseInput:

    def _state_with_window(self, element_id="5"):
        ctrl = _mock_control(200, 300, 400, 700)
        win  = MagicMock()
        win_rect = MagicMock()
        win_rect.left, win_rect.top, win_rect.right, win_rect.bottom = 0, 0, 1920, 1080
        win.rectangle.return_value = win_rect
        mock_state = MagicMock()
        mock_state.control_dict = {element_id: ctrl}
        mock_state.selected_app_window = win
        return mock_state

    def test_negative_wheel_dist_scrolls_down(self):
        client = _make_client()
        mock_state = self._state_with_window("5")
        with patch("careerbridge.ufo_executor.UIServerState", return_value=mock_state), \
             patch("careerbridge.ufo_executor._execute_scroll") as mock_scroll, \
             patch("careerbridge.ufo_executor._window_focus"):
            cmd = _cmd("wheel_mouse_input", params={"id": "5", "name": "Page", "wheel_dist": -3})
            result = run(client.execute_actions([cmd]))

        args = mock_scroll.call_args[0]
        assert args[2] == "down"
        assert args[3] == 3
        assert result[0].status == ResultStatus.SUCCESS

    def test_positive_wheel_dist_scrolls_up(self):
        client = _make_client()
        mock_state = self._state_with_window("5")
        with patch("careerbridge.ufo_executor.UIServerState", return_value=mock_state), \
             patch("careerbridge.ufo_executor._execute_scroll") as mock_scroll, \
             patch("careerbridge.ufo_executor._window_focus"):
            cmd = _cmd("wheel_mouse_input", params={"id": "5", "name": "Page", "wheel_dist": 2})
            result = run(client.execute_actions([cmd]))

        args = mock_scroll.call_args[0]
        assert args[2] == "up"
        assert args[3] == 2

    def test_zero_wheel_dist_is_noop(self):
        client = _make_client()
        mock_state = self._state_with_window()
        with patch("careerbridge.ufo_executor.UIServerState", return_value=mock_state), \
             patch("careerbridge.ufo_executor._execute_scroll") as mock_scroll, \
             patch("careerbridge.ufo_executor._window_focus"):
            cmd = _cmd("wheel_mouse_input", params={"id": "5", "name": "Page", "wheel_dist": 0})
            result = run(client.execute_actions([cmd]))

        mock_scroll.assert_not_called()
        assert result[0].status == ResultStatus.SUCCESS

    def test_window_focus_called_not_dom_click(self):
        """Ensures we call _window_focus (set_focus) instead of a DOM click."""
        client = _make_client()
        mock_state = self._state_with_window("5")
        with patch("careerbridge.ufo_executor.UIServerState", return_value=mock_state), \
             patch("careerbridge.ufo_executor._execute_scroll"), \
             patch("careerbridge.ufo_executor._window_focus") as mock_focus, \
             patch("careerbridge.ufo_executor._execute_click") as mock_click:
            cmd = _cmd("wheel_mouse_input", params={"id": "5", "name": "Page", "wheel_dist": -1})
            run(client.execute_actions([cmd]))

        mock_focus.assert_called_once()
        mock_click.assert_not_called()   # DOM click must NOT be used for scroll focus

    def test_falls_back_to_window_center_if_element_missing(self):
        client = _make_client()
        mock_state = MagicMock()
        mock_state.control_dict = {}
        win = MagicMock()
        win_rect = MagicMock()
        win_rect.left, win_rect.top, win_rect.right, win_rect.bottom = 0, 0, 800, 600
        win.rectangle.return_value = win_rect
        mock_state.selected_app_window = win
        with patch("careerbridge.ufo_executor.UIServerState", return_value=mock_state), \
             patch("careerbridge.ufo_executor._execute_scroll") as mock_scroll, \
             patch("careerbridge.ufo_executor._window_focus"):
            cmd = _cmd("wheel_mouse_input", params={"id": "99", "name": "x", "wheel_dist": -1})
            run(client.execute_actions([cmd]))

        args = mock_scroll.call_args[0]
        assert args[0] == 400   # window center x
        assert args[1] == 300   # window center y


# ── keyboard_input ────────────────────────────────────────────────────────────

class TestKeyboardInput:

    def test_enter_key_mapped_correctly(self):
        client = _make_client()
        with patch("careerbridge.ufo_executor.pyautogui") as mock_pa:
            cmd = _cmd("keyboard_input", params={"id": "1", "name": "x", "keys": "{ENTER}"})
            result = run(client.execute_actions([cmd]))

        mock_pa.press.assert_called_with("enter", _pause=False)
        assert result[0].status == ResultStatus.SUCCESS

    def test_ctrl_l_hotkey_mapped_correctly(self):
        client = _make_client()
        with patch("careerbridge.ufo_executor.pyautogui") as mock_pa:
            cmd = _cmd("keyboard_input", params={"id": "1", "name": "x", "keys": "{VK_CONTROL}l"})
            result = run(client.execute_actions([cmd]))

        mock_pa.hotkey.assert_called_with("ctrl", "l", _pause=False)

    def test_ctrl_a_hotkey_mapped_correctly(self):
        client = _make_client()
        with patch("careerbridge.ufo_executor.pyautogui") as mock_pa:
            cmd = _cmd("keyboard_input", params={"id": "1", "name": "x", "keys": "{VK_CONTROL}a"})
            run(client.execute_actions([cmd]))

        mock_pa.hotkey.assert_called_with("ctrl", "a", _pause=False)

    def test_unmapped_key_returns_success_no_crash(self):
        """Unknown key sequences must not crash — skip and return SUCCESS."""
        client = _make_client()
        with patch("careerbridge.ufo_executor.pyautogui") as mock_pa:
            cmd = _cmd("keyboard_input", params={"id": "1", "name": "x", "keys": "{F5}"})
            result = run(client.execute_actions([cmd]))

        mock_pa.press.assert_not_called()
        mock_pa.hotkey.assert_not_called()
        assert result[0].status == ResultStatus.SUCCESS

    def test_all_mapped_keys_have_valid_structure(self):
        """Every entry in _KEY_MAP must be ('press', key) or ('hotkey', *keys)."""
        for seq, action in _KEY_MAP.items():
            assert action[0] in ("press", "hotkey"), f"Bad action type for {seq!r}: {action[0]!r}"
            assert len(action) >= 2, f"Too short for {seq!r}: {action}"


# ── Exception safety ──────────────────────────────────────────────────────────

class TestExceptionSafety:

    def test_execute_click_exception_returns_failure(self):
        client = _make_client()
        ctrl = _mock_control()
        mock_state = MagicMock()
        mock_state.control_dict = {"1": ctrl}
        with patch("careerbridge.ufo_executor.UIServerState", return_value=mock_state), \
             patch("careerbridge.ufo_executor._execute_click", side_effect=RuntimeError("screen locked")):
            cmd = _cmd("click_input", params={"id": "1", "name": "x"})
            result = run(client.execute_actions([cmd]))

        assert result[0].status == ResultStatus.FAILURE
        assert "screen locked" in result[0].error

    def test_execute_type_exception_returns_failure(self):
        client = _make_client()
        ctrl = _mock_control()
        mock_state = MagicMock()
        mock_state.control_dict = {"1": ctrl}
        with patch("careerbridge.ufo_executor.UIServerState", return_value=mock_state), \
             patch("careerbridge.ufo_executor._execute_type", side_effect=RuntimeError("focus lost")):
            cmd = _cmd("set_edit_text", params={"id": "1", "name": "x", "text": "y"})
            result = run(client.execute_actions([cmd]))

        assert result[0].status == ResultStatus.FAILURE

    def test_multiple_commands_failure_does_not_abort_rest(self):
        """A failure on one command must not prevent subsequent commands from running."""
        client = _make_client()
        mock_state = MagicMock()
        mock_state.control_dict = {}
        mock_state.selected_app_window = None
        with patch("careerbridge.ufo_executor.UIServerState", return_value=mock_state), \
             patch("careerbridge.ufo_executor._execute_scroll"), \
             patch("careerbridge.ufo_executor._window_focus"), \
             patch("careerbridge.ufo_executor.pyautogui"):
            cmds = [
                _cmd("click_input",       params={"id": "99", "name": "x"},             call_id="c1"),
                _cmd("keyboard_input",    params={"id": "1",  "name": "y", "keys": "{ENTER}"}, call_id="c2"),
            ]
            results = run(client.execute_actions(cmds))

        assert results[0].status == ResultStatus.FAILURE   # unknown element
        assert results[1].status == ResultStatus.SUCCESS   # keyboard still ran
