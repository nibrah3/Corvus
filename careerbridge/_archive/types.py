# types.py — Shared enum definitions for CareerBridge
# SCHEMA_VERSION: 1
# No dependencies on other CareerBridge modules.
# Changes to any enum require a version bump in schema.py.

from enum import Enum


class ElementType(Enum):
    BUTTON    = "button"
    RADIO     = "radio"
    CHECKBOX  = "checkbox"
    TEXT      = "text"
    INPUT     = "input"
    DROPDOWN  = "dropdown"
    LABEL     = "label"
    UNKNOWN   = "unknown"


class PerceptionSource(Enum):
    UIA    = "uia"     # Windows UI Automation — preferred
    OCR    = "ocr"     # PaddleOCR region — fallback
    CV     = "cv"      # OpenCV structure — Phase 2
    MANUAL = "manual"  # test fixtures only


class ActionType(Enum):
    CLICK  = "click"
    TYPE   = "type"
    SCROLL = "scroll"
    FOCUS  = "focus"
    WAIT   = "wait"


class FSMState(Enum):
    INIT     = "init"
    NAVIGATE = "navigate"
    WAIT_UI  = "wait_ui"
    EXTRACT  = "extract"
    REASON   = "reason"
    EXECUTE  = "execute"
    VERIFY   = "verify"
    COMPLETE = "complete"
    ERROR    = "error"


class MouseSpeed(Enum):
    SLOW   = "slow"
    MEDIUM = "medium"
    FAST   = "fast"


class ChangeType(Enum):
    NONE       = "none"        # frames identical (below noise floor)
    MINOR      = "minor"       # <0.5% pixels changed (cursor blink, caret)
    CONTENT    = "content"     # 0.5–15% changed (text typed, element updated)
    STRUCTURAL = "structural"  # >15% changed (page load, navigation, popup)


class ConfidenceBand(Enum):
    HIGH   = "high"    # > 0.85 — proceed
    MEDIUM = "medium"  # 0.65–0.85 — proceed
    LOW    = "low"     # < 0.65 — halt, trigger fallback


def confidence_band(score: float) -> ConfidenceBand:
    """Convert a raw 0.0–1.0 confidence float to a discrete ConfidenceBand."""
    if score > 0.85:
        return ConfidenceBand.HIGH
    if score >= 0.65:
        return ConfidenceBand.MEDIUM
    return ConfidenceBand.LOW
