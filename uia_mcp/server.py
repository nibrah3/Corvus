"""
UIA MCP server — Windows UI Automation element tree reader.

Tools:
  find_elements   — find interactive elements in the focused window
  get_element     — get a single element by id, name, or type
  focused_window  — info about the current foreground window

Why UIA alongside screenshots:
  Screenshots give Claude visual context.
  UIA gives exact pixel coordinates (rect) for every button, field, radio button.
  Together: Claude sees WHAT to interact with (screenshot) and WHERE exactly (UIA).
  No coordinate guessing from vision alone.

Uses pywinauto's uia_controls which wraps Windows UIAutomation COM API.
No admin rights needed. Works with Chrome, Edge, Win32, WinForms, WPF.
"""
from __future__ import annotations

import time
from typing import Optional

from _minmcp import MinMCP

mcp = MinMCP("uia")

# ── Element type normalisation ────────────────────────────────────────────────

_TYPE_MAP = {
    "Button":       "button",
    "CheckBox":     "checkbox",
    "RadioButton":  "radio",
    "Edit":         "input",
    "ComboBox":     "select",
    "ListItem":     "list_item",
    "MenuItem":     "menu_item",
    "Hyperlink":    "link",
    "Text":         "text",
    "Document":     "document",
    "Pane":         "pane",
    "Image":        "image",
}

_INTERACTIVE = frozenset({"button", "checkbox", "radio", "input", "select", "link", "list_item"})


def _rect_dict(rect) -> dict:
    return {
        "left":   rect.left,
        "top":    rect.top,
        "right":  rect.right,
        "bottom": rect.bottom,
        "cx":     (rect.left + rect.right) // 2,
        "cy":     (rect.top  + rect.bottom) // 2,
        "width":  rect.right  - rect.left,
        "height": rect.bottom - rect.top,
    }


def _element_dict(el, idx: int) -> dict:
    try:
        rect  = el.rectangle()
        rdict = _rect_dict(rect)
    except Exception:
        rdict = {}

    ctrl_type = getattr(el, "element_info", None)
    if ctrl_type:
        raw_type = getattr(ctrl_type, "control_type", "") or ""
    else:
        raw_type = ""

    el_type = _TYPE_MAP.get(raw_type, raw_type.lower() or "unknown")

    try:
        name = el.window_text() or ""
    except Exception:
        name = ""

    try:
        enabled = el.is_enabled()
    except Exception:
        enabled = True

    return {
        "id":      idx,
        "type":    el_type,
        "name":    name,
        "enabled": enabled,
        "rect":    rdict,
        "interactive": el_type in _INTERACTIVE,
    }


# ── Tools ─────────────────────────────────────────────────────────────────────

@mcp.tool()
def find_elements(
    interactive_only: bool = True,
    max_depth: int = 8,
    window_title: Optional[str] = None,
) -> dict:
    """
    Walk the UI Automation tree of the focused (or named) window and return
    all visible elements with their exact screen coordinates.

    Use this alongside screenshot() — screenshot shows Claude the visual layout,
    find_elements() gives exact click coordinates for every button/field/radio.

    Args:
        interactive_only: If True (default), return only clickable elements
                          (buttons, inputs, checkboxes, radios, links).
                          False returns all elements including static text.
        max_depth:        How deep to walk the tree (default 8).
                          Increase for deeply nested web content.
        window_title:     Partial title of window to target.
                          None = use the current foreground window.

    Returns:
        {window: str, element_count: int, elements: [...]}
        Each element: {id, type, name, enabled, rect, interactive}
        rect: {left, top, right, bottom, cx, cy, width, height}
        cx/cy = centre point — pass directly to humanized_click().
    """
    try:
        from pywinauto import Desktop, Application
        from pywinauto.uia_element_info import UIAElementInfo
    except ImportError:
        return {"error": "pywinauto not installed. pip install pywinauto"}

    try:
        if window_title:
            desktop = Desktop(backend="uia")
            windows = desktop.windows(title_re=f".*{window_title}.*")
            if not windows:
                return {"error": f"No window matching '{window_title}'"}
            win = windows[0]
        else:
            import ctypes
            hwnd = ctypes.windll.user32.GetForegroundWindow()
            if not hwnd:
                return {"error": "No foreground window"}
            app = Application(backend="uia").connect(handle=hwnd)
            win = app.window(handle=hwnd)

        win_title = win.window_text() or "unknown"
    except Exception as exc:
        return {"error": f"Window connection failed: {exc}"}

    try:
        descendants = win.descendants(depth=max_depth)
    except Exception as exc:
        return {"error": f"Tree walk failed: {exc}"}

    elements = []
    for idx, el in enumerate(descendants):
        try:
            ed = _element_dict(el, idx)
            if not ed["rect"]:
                continue
            if interactive_only and not ed["interactive"]:
                continue
            # Skip zero-size elements
            if ed["rect"].get("width", 0) < 2 or ed["rect"].get("height", 0) < 2:
                continue
            elements.append(ed)
        except Exception:
            continue

    return {
        "window":        win_title,
        "element_count": len(elements),
        "elements":      elements,
    }


@mcp.tool()
def get_element(
    name: Optional[str] = None,
    element_type: Optional[str] = None,
    index: Optional[int] = None,
    window_title: Optional[str] = None,
) -> dict:
    """
    Find a single specific element by name and/or type.

    Args:
        name:         Partial text match on element name/label (case-insensitive).
        element_type: Filter by type: "button", "input", "radio", "checkbox",
                      "link", "select", "list_item".
        index:        If multiple matches, pick the Nth one (0-based).
        window_title: Partial window title. None = foreground window.

    Returns:
        Single element dict with rect containing cx/cy for clicking.
        If not found: {"error": "not found", "searched_name": ..., "searched_type": ...}
    """
    result = find_elements(interactive_only=False, window_title=window_title)
    if "error" in result:
        return result

    elements = result["elements"]
    matches = elements

    if element_type:
        matches = [e for e in matches if e["type"] == element_type.lower()]

    if name:
        nl = name.lower()
        matches = [e for e in matches if nl in e["name"].lower()]

    if not matches:
        return {
            "error":          "not found",
            "searched_name":  name,
            "searched_type":  element_type,
            "available_types": list({e["type"] for e in elements}),
        }

    pick = matches[index or 0]
    return pick


@mcp.tool()
def focused_window() -> dict:
    """
    Return information about the current foreground window.

    Returns:
        {title, handle, rect, process_name}
    """
    import ctypes
    import ctypes.wintypes as wt

    hwnd = ctypes.windll.user32.GetForegroundWindow()
    if not hwnd:
        return {"error": "no foreground window"}

    # Title
    buf = ctypes.create_unicode_buffer(512)
    ctypes.windll.user32.GetWindowTextW(hwnd, buf, 512)
    title = buf.value

    # Rect
    rect = wt.RECT()
    ctypes.windll.user32.GetWindowRect(hwnd, ctypes.byref(rect))

    # Process name
    pid = wt.DWORD()
    ctypes.windll.user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
    try:
        import psutil
        proc_name = psutil.Process(pid.value).name()
    except Exception:
        proc_name = f"pid:{pid.value}"

    return {
        "title":        title,
        "handle":       hwnd,
        "rect":         _rect_dict(type("R", (), {"left": rect.left, "top": rect.top,
                                                   "right": rect.right, "bottom": rect.bottom})()),
        "process_name": proc_name,
    }


if __name__ == "__main__":
    mcp.run()
