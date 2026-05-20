# uia.py — Phase 4: Windows UI Automation element extractor
# SCHEMA_VERSION: 1
#
# Single responsibility: query pywinauto/UIA for native Windows controls
# and return them as UIElement instances.
#
# Scope: native controls only (dialogs, popups, OS chrome).
# Browser web content (IXBrowser/Chromium) is NOT visible here unless
# Chrome runs with --force-renderer-accessibility.
#
# MUST NOT: capture pixels, run OCR, make navigation decisions.

from __future__ import annotations

import warnings
from typing import Optional

from ..errors import ErrorCode, PerceptionError
from ..schema import BoundingBox, UIElement
from ..types import ElementType, PerceptionSource

# ── Backend detection ─────────────────────────────────────────────────────────

try:
    import pywinauto as _pwa
    _PWA_AVAILABLE = True
except Exception:
    _PWA_AVAILABLE = False

# ── Control type mapping ──────────────────────────────────────────────────────

_CONTROL_TYPE_MAP: dict[str, ElementType] = {
    "button":      ElementType.BUTTON,
    "radiobutton": ElementType.RADIO,
    "checkbox":    ElementType.CHECKBOX,
    "edit":        ElementType.INPUT,
    "document":    ElementType.INPUT,
    "text":        ElementType.TEXT,
    "static":      ElementType.TEXT,
    "combobox":    ElementType.DROPDOWN,
    "listitem":    ElementType.TEXT,
}

_SKIP_CONTROL_TYPES = frozenset({
    "titlebar", "scrollbar", "window", "pane", "toolbar",
    "statusbar", "tabitem", "tab", "grouping", "separator",
})

# ── Helpers ───────────────────────────────────────────────────────────────────

def _map_control_type(ctrl_type: str) -> Optional[ElementType]:
    """Map a pywinauto control_type string to ElementType. Returns None to skip."""
    key = ctrl_type.lower().replace(" ", "")
    if key in _SKIP_CONTROL_TYPES:
        return None
    return _CONTROL_TYPE_MAP.get(key, ElementType.UNKNOWN)


def _rect_to_bbox(rect) -> Optional[BoundingBox]:
    """Convert a pywinauto RECT to BoundingBox. Returns None if degenerate."""
    try:
        w = rect.right - rect.left
        h = rect.bottom - rect.top
        if w <= 0 or h <= 0:
            return None
        return BoundingBox(x=rect.left, y=rect.top, w=w, h=h)
    except Exception:
        return None


def _bbox_in_region(bbox: BoundingBox, region: Optional[BoundingBox]) -> bool:
    """Return True if bbox intersects region (or region is None)."""
    if region is None:
        return True
    return (
        bbox.x < region.x + region.w
        and bbox.x + bbox.w > region.x
        and bbox.y < region.y + region.h
        and bbox.y + bbox.h > region.y
    )


# ── Public API ────────────────────────────────────────────────────────────────

def extract_uia_elements(
    window_title: str,
    frame_id: int,
    region: Optional[BoundingBox] = None,
    min_confidence: float = 0.9,
) -> list[UIElement]:
    """
    Extract native Windows UI elements from the window matching window_title.

    Args:
        window_title:   Substring match against window title (case-insensitive).
        frame_id:       frame_id to stamp on returned UIElements.
        region:         If given, only return elements whose bbox intersects region.
        min_confidence: Minimum confidence to include an element (UIA = 0.9 fixed).

    Returns:
        List of UIElement instances, possibly empty.

    Raises:
        PerceptionError(E202) if pywinauto is not installed.
        PerceptionError(E204) if the window cannot be connected to.
    """
    if not _PWA_AVAILABLE:
        raise PerceptionError(
            ErrorCode.PERCEPTION_UIA_UNAVAILABLE,
            "pywinauto is not installed. Run: pip install pywinauto",
        )

    try:
        app = _pwa.Application(backend="uia").connect(
            title_re=f"(?i).*{window_title}.*",
            timeout=3,
        )
        win = app.top_window()
    except Exception as e:
        raise PerceptionError(
            ErrorCode.PERCEPTION_TIMEOUT,
            f"Could not connect to window matching {window_title!r}: {e}",
            {"window_title": window_title},
        ) from e

    elements: list[UIElement] = []

    try:
        descendants = win.descendants()
    except Exception as e:
        raise PerceptionError(
            ErrorCode.PERCEPTION_TIMEOUT,
            f"Failed to query UIA descendants for {window_title!r}: {e}",
            {"window_title": window_title},
        ) from e

    for ctrl in descendants:
        try:
            ctrl_type = ctrl.element_info.control_type or ""
            element_type = _map_control_type(ctrl_type)
            if element_type is None:
                continue

            rect = ctrl.element_info.rectangle
            bbox = _rect_to_bbox(rect)
            if bbox is None:
                continue

            if not _bbox_in_region(bbox, region):
                continue

            try:
                text = (ctrl.element_info.name or "").strip()
            except Exception:
                text = ""

            elements.append(UIElement(
                element_type=element_type,
                text=text,
                bbox=bbox,
                confidence=0.9,
                source=PerceptionSource.UIA,
                frame_id=frame_id,
            ))
        except Exception:
            # Never let a single bad control abort the whole extraction
            continue

    return elements
