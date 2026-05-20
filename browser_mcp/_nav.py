"""
CDP-free browser navigation via OS keyboard shortcuts.

All actions are pure keystrokes routed through the humanizer MCP's
_keyboard module. No Chrome DevTools Protocol. No extension injection.

Navigation primitives:
  navigate(url)       Ctrl+L → type URL → Enter
  go_back()           Alt+Left
  go_forward()        Alt+Right
  reload()            Ctrl+R (or F5)
  new_tab()           Ctrl+T
  close_tab()         Ctrl+W
  switch_tab(n)       Ctrl+n  (1-based, 1..8; 9 = last tab)
  find_on_page(text)  Ctrl+F → type → Escape

Tab focus:
  focus_address_bar() Ctrl+L
  focus_page()        Escape (closes address bar if open, focuses page)

Scroll:
  page_down()         Space or Page_Down
  page_up()           Shift+Space or Page_Up
  scroll_top()        Ctrl+Home
  scroll_bottom()     Ctrl+End
"""
from __future__ import annotations

import time

# Import humanizer keyboard directly (same process, no MCP overhead for internals)
from humanizer_mcp._keyboard import type_text, press_key, hotkey
from humanizer_mcp._profile import BehaviorProfile
from random import Random


def _profile() -> tuple[BehaviorProfile, Random]:
    return BehaviorProfile(), Random()


def navigate(url: str, profile: BehaviorProfile | None = None, rng: Random | None = None) -> None:
    """Navigate to URL via Ctrl+L → type → Enter."""
    p, r = profile or BehaviorProfile(), rng or Random()
    hotkey(["ctrl", "l"], p, r)
    time.sleep(0.15)
    # Select-all first to clear any existing address bar content
    hotkey(["ctrl", "a"], p, r)
    time.sleep(0.05)
    type_text(url, p, r)
    time.sleep(0.1)
    press_key("enter", p, r)
    time.sleep(0.2)  # give page a moment to start loading


def go_back(profile: BehaviorProfile | None = None, rng: Random | None = None) -> None:
    p, r = profile or BehaviorProfile(), rng or Random()
    hotkey(["alt", "left"], p, r)


def go_forward(profile: BehaviorProfile | None = None, rng: Random | None = None) -> None:
    p, r = profile or BehaviorProfile(), rng or Random()
    hotkey(["alt", "right"], p, r)


def reload(profile: BehaviorProfile | None = None, rng: Random | None = None) -> None:
    p, r = profile or BehaviorProfile(), rng or Random()
    press_key("f5", p, r)


def new_tab(profile: BehaviorProfile | None = None, rng: Random | None = None) -> None:
    p, r = profile or BehaviorProfile(), rng or Random()
    hotkey(["ctrl", "t"], p, r)
    time.sleep(0.3)


def close_tab(profile: BehaviorProfile | None = None, rng: Random | None = None) -> None:
    p, r = profile or BehaviorProfile(), rng or Random()
    hotkey(["ctrl", "w"], p, r)
    time.sleep(0.2)


def switch_tab(n: int, profile: BehaviorProfile | None = None, rng: Random | None = None) -> None:
    """Switch to tab n (1-based). n=9 goes to last tab. Clamps to 1-9."""
    p, r = profile or BehaviorProfile(), rng or Random()
    n = max(1, min(9, n))
    hotkey(["ctrl", str(n)], p, r)
    time.sleep(0.15)


def focus_page(profile: BehaviorProfile | None = None, rng: Random | None = None) -> None:
    """Escape from address bar / dismiss any overlay; focus main page content."""
    p, r = profile or BehaviorProfile(), rng or Random()
    press_key("escape", p, r)
    time.sleep(0.05)


def scroll_top(profile: BehaviorProfile | None = None, rng: Random | None = None) -> None:
    p, r = profile or BehaviorProfile(), rng or Random()
    hotkey(["ctrl", "home"], p, r)


def scroll_bottom(profile: BehaviorProfile | None = None, rng: Random | None = None) -> None:
    p, r = profile or BehaviorProfile(), rng or Random()
    hotkey(["ctrl", "end"], p, r)
