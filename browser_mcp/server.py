"""
Browser MCP server — CDP-free Chrome control via OS-level keystrokes.

Tools:
  launch_chrome      Launch Chrome with accessibility flags (no CDP)
  navigate           Go to URL via Ctrl+L (no CDP)
  go_back            Browser back (Alt+Left)
  go_forward         Browser forward (Alt+Right)
  reload             Reload page (F5)
  new_tab            Open new tab (Ctrl+T)
  close_tab          Close current tab (Ctrl+W)
  switch_tab         Switch to tab N (Ctrl+N)
  wait_for_load      Wait for page to finish loading (title stability)
  scroll_to_top      Jump to top of page (Ctrl+Home)
  scroll_to_bottom   Jump to bottom (Ctrl+End)
  focus_page         Dismiss address bar / overlays (Escape)

Why no CDP:
  CDP requires --remote-debugging-port flag which appears in process cmdline
  and is detectable by assessment anti-bot systems. All navigation here is
  pure OS keyboard input through the humanizer, same as a human would type.

Chrome UIA accessibility:
  launch_chrome includes --force-renderer-accessibility so the UIA MCP can
  see all DOM elements (radio buttons, inputs, buttons) with exact coordinates.
  Without this flag, Chrome exposes only 3 native window controls via UIA.
"""
from __future__ import annotations

from typing import Optional

from _minmcp import MinMCP

mcp = MinMCP("browser")

# ── Tool implementations ───────────────────────────────────────────────────────

@mcp.tool()
def launch_chrome(url: str = "", chrome_path: str = "") -> dict:
    """
    Launch Chrome with UIA accessibility enabled. No CDP flags.

    Includes --force-renderer-accessibility so that find_elements() from the
    UIA MCP can see all page elements (radio buttons, inputs, buttons).

    Args:
        url:         URL to open on launch. Empty = open new tab page.
        chrome_path: Full path to chrome.exe. Leave empty to auto-detect.

    Returns:
        {pid, chrome_path, url, launched_at}
    """
    try:
        from browser_mcp._chrome import launch_chrome as _launch
        return _launch(url=url, chrome_path=chrome_path)
    except Exception as exc:
        return {"error": str(exc)}


@mcp.tool()
def navigate(url: str, profile_seed: Optional[int] = None) -> dict:
    """
    Navigate to a URL via Ctrl+L → type URL → Enter. No CDP.

    Chrome must be the foreground window before calling this.
    After this returns, call wait_for_load() to confirm the page is ready.

    Args:
        url:          Full URL including https://
        profile_seed: Typing timing seed (matches humanizer profile_seed for
                      consistent fingerprint across a session).

    Returns:
        {status: "navigated", url: str}
    """
    try:
        from browser_mcp._nav import navigate as _nav
        from humanizer_mcp._profile import BehaviorProfile
        from random import Random
        rng = Random(profile_seed) if profile_seed is not None else Random()
        _nav(url=url, profile=BehaviorProfile(), rng=rng)
        return {"status": "navigated", "url": url}
    except Exception as exc:
        return {"error": str(exc)}


@mcp.tool()
def go_back(profile_seed: Optional[int] = None) -> dict:
    """Navigate back (Alt+Left)."""
    try:
        from browser_mcp._nav import go_back as _back
        from humanizer_mcp._profile import BehaviorProfile
        from random import Random
        _back(profile=BehaviorProfile(), rng=Random(profile_seed or 0))
        return {"status": "back"}
    except Exception as exc:
        return {"error": str(exc)}


@mcp.tool()
def go_forward(profile_seed: Optional[int] = None) -> dict:
    """Navigate forward (Alt+Right)."""
    try:
        from browser_mcp._nav import go_forward as _fwd
        from humanizer_mcp._profile import BehaviorProfile
        from random import Random
        _fwd(profile=BehaviorProfile(), rng=Random(profile_seed or 0))
        return {"status": "forward"}
    except Exception as exc:
        return {"error": str(exc)}


@mcp.tool()
def reload(profile_seed: Optional[int] = None) -> dict:
    """Reload the current page (F5)."""
    try:
        from browser_mcp._nav import reload as _reload
        from humanizer_mcp._profile import BehaviorProfile
        from random import Random
        _reload(profile=BehaviorProfile(), rng=Random(profile_seed or 0))
        return {"status": "reloaded"}
    except Exception as exc:
        return {"error": str(exc)}


@mcp.tool()
def new_tab(profile_seed: Optional[int] = None) -> dict:
    """Open a new tab (Ctrl+T)."""
    try:
        from browser_mcp._nav import new_tab as _new
        from humanizer_mcp._profile import BehaviorProfile
        from random import Random
        _new(profile=BehaviorProfile(), rng=Random(profile_seed or 0))
        return {"status": "new_tab_opened"}
    except Exception as exc:
        return {"error": str(exc)}


@mcp.tool()
def close_tab(profile_seed: Optional[int] = None) -> dict:
    """Close the current tab (Ctrl+W)."""
    try:
        from browser_mcp._nav import close_tab as _close
        from humanizer_mcp._profile import BehaviorProfile
        from random import Random
        _close(profile=BehaviorProfile(), rng=Random(profile_seed or 0))
        return {"status": "tab_closed"}
    except Exception as exc:
        return {"error": str(exc)}


@mcp.tool()
def switch_tab(n: int, profile_seed: Optional[int] = None) -> dict:
    """
    Switch to tab number N (1-based, Ctrl+N). N=9 goes to last tab.

    Args:
        n: Tab number 1-9.
    """
    try:
        from browser_mcp._nav import switch_tab as _switch
        from humanizer_mcp._profile import BehaviorProfile
        from random import Random
        _switch(n=n, profile=BehaviorProfile(), rng=Random(profile_seed or 0))
        return {"status": "switched", "tab": n}
    except Exception as exc:
        return {"error": str(exc)}


@mcp.tool()
def wait_for_load(timeout: float = 15.0, stable_ms: int = 600) -> dict:
    """
    Wait for the current Chrome page to finish loading.

    Polls the window title until it's stable (no longer changing and not
    showing "Loading..." or "..."). Does not use CDP Page.loadEventFired.

    Args:
        timeout:   Max seconds to wait (default 15).
        stable_ms: Title must not change for this many ms (default 600).

    Returns:
        {status: "loaded"|"timeout", title: str, elapsed_ms: int}
    """
    try:
        from browser_mcp._wait import wait_for_load as _wait
        return _wait(timeout=timeout, stable_ms=stable_ms)
    except Exception as exc:
        return {"error": str(exc)}


@mcp.tool()
def scroll_to_top(profile_seed: Optional[int] = None) -> dict:
    """Jump to top of page (Ctrl+Home)."""
    try:
        from browser_mcp._nav import scroll_top as _top
        from humanizer_mcp._profile import BehaviorProfile
        from random import Random
        _top(profile=BehaviorProfile(), rng=Random(profile_seed or 0))
        return {"status": "scrolled_top"}
    except Exception as exc:
        return {"error": str(exc)}


@mcp.tool()
def scroll_to_bottom(profile_seed: Optional[int] = None) -> dict:
    """Jump to bottom of page (Ctrl+End)."""
    try:
        from browser_mcp._nav import scroll_bottom as _bot
        from humanizer_mcp._profile import BehaviorProfile
        from random import Random
        _bot(profile=BehaviorProfile(), rng=Random(profile_seed or 0))
        return {"status": "scrolled_bottom"}
    except Exception as exc:
        return {"error": str(exc)}


@mcp.tool()
def focus_page(profile_seed: Optional[int] = None) -> dict:
    """
    Press Escape to dismiss address bar / close any overlay and return focus
    to page content. Safe to call before any keyboard-driven page interaction.
    """
    try:
        from browser_mcp._nav import focus_page as _focus
        from humanizer_mcp._profile import BehaviorProfile
        from random import Random
        _focus(profile=BehaviorProfile(), rng=Random(profile_seed or 0))
        return {"status": "page_focused"}
    except Exception as exc:
        return {"error": str(exc)}


if __name__ == "__main__":
    mcp.run()
