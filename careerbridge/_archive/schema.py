# schema.py — Data contracts for CareerBridge
# SCHEMA_VERSION: 1
#
# ALL schemas are frozen after Phase 0.
# Changes require:
#   1. Increment SCHEMA_VERSION
#   2. Write migration test
#   3. Update persistence.py reader
#
# Rules:
#   - frozen=True wherever dict is not required (immutable by construction)
#   - All validation in __post_init__ — no validation elsewhere
#   - IDs and hashes are computed, never passed by caller
#   - Every schema carries schema_version for forward-compatibility detection

from __future__ import annotations

import hashlib
import types as _types
from dataclasses import dataclass, field
from typing import Any, Optional

from .types import (
    ActionType,
    ElementType,
    MouseSpeed,
    PerceptionSource,
)

SCHEMA_VERSION: int = 1


# ── Sub-schemas (frozen) ──────────────────────────────────────────────────────

@dataclass(frozen=True)
class BoundingBox:
    x: int   # left edge in screen pixels (may be negative on multi-monitor)
    y: int   # top edge in screen pixels
    w: int   # width > 0
    h: int   # height > 0

    def __post_init__(self) -> None:
        if self.w <= 0:
            raise ValueError(f"BoundingBox.w must be > 0, got {self.w}")
        if self.h <= 0:
            raise ValueError(f"BoundingBox.h must be > 0, got {self.h}")

    @property
    def center_x(self) -> int:
        return self.x + self.w // 2

    @property
    def center_y(self) -> int:
        return self.y + self.h // 2


@dataclass(frozen=True)
class BigFive:
    openness:          int   # 0–100
    conscientiousness: int   # 0–100
    extraversion:      int   # 0–100
    agreeableness:     int   # 0–100
    neuroticism:       int   # 0–100

    def __post_init__(self) -> None:
        for name, val in (
            ("openness",          self.openness),
            ("conscientiousness", self.conscientiousness),
            ("extraversion",      self.extraversion),
            ("agreeableness",     self.agreeableness),
            ("neuroticism",       self.neuroticism),
        ):
            if not 0 <= val <= 100:
                raise ValueError(f"BigFive.{name} must be 0–100, got {val}")


@dataclass(frozen=True)
class ResponseBias:
    extreme_answer_rate:      float   # 0.0–1.0: how often picks Strongly Agree/Disagree
    neutral_preference:       float   # 0.0–1.0: how often picks middle option
    social_desirability_bias: float   # 0.0–1.0: tendency to answer "ideally"
    consistency_strength:     float   # 0.0–1.0: how stable answers are across rephrases

    def __post_init__(self) -> None:
        for name, val in (
            ("extreme_answer_rate",      self.extreme_answer_rate),
            ("neutral_preference",       self.neutral_preference),
            ("social_desirability_bias", self.social_desirability_bias),
            ("consistency_strength",     self.consistency_strength),
        ):
            if not 0.0 <= val <= 1.0:
                raise ValueError(f"ResponseBias.{name} must be 0.0–1.0, got {val}")


@dataclass(frozen=True)
class LinguisticTraits:
    verbosity: float   # 0.0–1.0: terse vs elaborate
    formality:  float   # 0.0–1.0: casual vs professional
    optimism:   float   # 0.0–1.0: pessimistic vs optimistic framing

    def __post_init__(self) -> None:
        for name, val in (
            ("verbosity", self.verbosity),
            ("formality",  self.formality),
            ("optimism",   self.optimism),
        ):
            if not 0.0 <= val <= 1.0:
                raise ValueError(f"LinguisticTraits.{name} must be 0.0–1.0, got {val}")


@dataclass(frozen=True)
class BehaviorFingerprint:
    typing_wpm:    int         # 20–200 words per minute
    error_rate:    float       # 0.0–0.20 (fraction of chars mistyped then corrected)
    mouse_speed:   MouseSpeed
    pause_min_ms:  int         # >= 0
    pause_max_ms:  int         # > pause_min_ms

    def __post_init__(self) -> None:
        if not 20 <= self.typing_wpm <= 200:
            raise ValueError(f"BehaviorFingerprint.typing_wpm must be 20–200, got {self.typing_wpm}")
        if not 0.0 <= self.error_rate <= 0.20:
            raise ValueError(f"BehaviorFingerprint.error_rate must be 0.0–0.20, got {self.error_rate}")
        if self.pause_min_ms < 0:
            raise ValueError(f"BehaviorFingerprint.pause_min_ms must be >= 0, got {self.pause_min_ms}")
        if self.pause_max_ms <= self.pause_min_ms:
            raise ValueError(
                f"BehaviorFingerprint.pause_max_ms ({self.pause_max_ms}) "
                f"must be > pause_min_ms ({self.pause_min_ms})"
            )


# ── Primary schemas ───────────────────────────────────────────────────────────

@dataclass(frozen=True)
class UIElement:
    """
    A single detected UI control.
    element_id is computed automatically — do not pass it.
    source indicates which perception layer produced this element.
    """
    element_type:   ElementType
    text:           str
    bbox:           BoundingBox
    confidence:     float          # 0.0–1.0
    source:         PerceptionSource
    frame_id:       int
    element_id:     str            = field(init=False)
    schema_version: int            = field(default=SCHEMA_VERSION, init=False)

    def __post_init__(self) -> None:
        if not 0.0 <= self.confidence <= 1.0:
            raise ValueError(f"UIElement.confidence must be 0.0–1.0, got {self.confidence}")
        if self.frame_id < 0:
            raise ValueError(f"UIElement.frame_id must be >= 0, got {self.frame_id}")
        computed = _element_hash(self.text, self.bbox, self.source)
        object.__setattr__(self, "element_id", computed)
        object.__setattr__(self, "schema_version", SCHEMA_VERSION)


def _element_hash(text: str, bbox: BoundingBox, source: PerceptionSource) -> str:
    raw = f"{text}|{bbox.x},{bbox.y},{bbox.w},{bbox.h}|{source.value}"
    return hashlib.sha256(raw.encode()).hexdigest()[:16]


@dataclass(frozen=True)
class UIState:
    """
    Complete snapshot of the observable UI at one frame.
    state_hash is computed automatically from frame_id + element ids.
    """
    frame_id:       int
    timestamp:      float
    window_title:   str
    window_bbox:    BoundingBox
    elements:       tuple[UIElement, ...]
    state_hash:     str            = field(init=False)
    schema_version: int            = field(default=SCHEMA_VERSION, init=False)

    def __post_init__(self) -> None:
        if self.frame_id < 0:
            raise ValueError(f"UIState.frame_id must be >= 0, got {self.frame_id}")
        if self.timestamp <= 0:
            raise ValueError(f"UIState.timestamp must be > 0, got {self.timestamp}")
        if not self.window_title:
            raise ValueError("UIState.window_title must not be empty")
        if not isinstance(self.elements, tuple):
            raise TypeError(f"UIState.elements must be a tuple, got {type(self.elements).__name__}")
        computed = _state_hash(self.frame_id, self.elements)
        object.__setattr__(self, "state_hash", computed)
        object.__setattr__(self, "schema_version", SCHEMA_VERSION)


def _state_hash(frame_id: int, elements: tuple[UIElement, ...]) -> str:
    raw = str(frame_id) + "|" + "|".join(e.element_id for e in elements)
    return hashlib.sha256(raw.encode()).hexdigest()[:16]


@dataclass
class Action:
    """
    A single executable action targeting one UIElement.
    payload is frozen to MappingProxyType after construction.
    Valid payloads per action_type:
      CLICK:  {} (empty)
      TYPE:   {"text": str}
      SCROLL: {"direction": "up"|"down", "amount": int > 0}
      FOCUS:  {} (empty)
      WAIT:   {"condition": str}
    """
    action_id:        str
    action_type:      ActionType
    target_element_id: str
    payload:          dict[str, Any]
    profile_id:       str
    frame_id:         int
    schema_version:   int = field(default=SCHEMA_VERSION, init=False)

    def __post_init__(self) -> None:
        if not self.action_id:
            raise ValueError("Action.action_id must not be empty")
        if not self.target_element_id:
            raise ValueError("Action.target_element_id must not be empty")
        if not self.profile_id:
            raise ValueError("Action.profile_id must not be empty")
        if self.frame_id < 0:
            raise ValueError(f"Action.frame_id must be >= 0, got {self.frame_id}")
        self._validate_payload()
        self.payload = _types.MappingProxyType(self.payload)
        self.schema_version = SCHEMA_VERSION

    def _validate_payload(self) -> None:
        t = self.action_type
        if t == ActionType.TYPE:
            if "text" not in self.payload or not isinstance(self.payload["text"], str):
                raise ValueError("Action TYPE payload must contain 'text': str")
        elif t == ActionType.SCROLL:
            if self.payload.get("direction") not in ("up", "down"):
                raise ValueError("Action SCROLL payload.direction must be 'up' or 'down'")
            amt = self.payload.get("amount")
            if not isinstance(amt, int) or amt <= 0:
                raise ValueError("Action SCROLL payload.amount must be int > 0")
        elif t == ActionType.WAIT:
            if "condition" not in self.payload or not isinstance(self.payload["condition"], str):
                raise ValueError("Action WAIT payload must contain 'condition': str")
        elif t in (ActionType.CLICK, ActionType.FOCUS):
            pass  # empty payload is valid


@dataclass
class SOPStep:
    """
    One step in a navigation SOP.
    Uses semantic anchors (text to find) — never pixel coordinates.
    """
    step_index:     int
    action_type:    ActionType
    anchor_text:    str          # text to locate the target element
    wait_for:       str          # condition to wait for after action
    payload:        dict[str, Any]
    schema_version: int = field(default=SCHEMA_VERSION, init=False)

    def __post_init__(self) -> None:
        if self.step_index < 0:
            raise ValueError(f"SOPStep.step_index must be >= 0, got {self.step_index}")
        if not self.anchor_text:
            raise ValueError("SOPStep.anchor_text must not be empty")
        if not self.wait_for:
            raise ValueError("SOPStep.wait_for must not be empty")
        self.payload = _types.MappingProxyType(self.payload)
        self.schema_version = SCHEMA_VERSION


@dataclass(frozen=True)
class SOP:
    """
    Navigation sequence for one site. Stores mechanics only — never answers.
    sop_id = first 16 chars of MD5(normalized base URL).
    steps must have contiguous 0-based step_index values.
    """
    sop_id:         str
    site_url:       str
    steps:          tuple[SOPStep, ...]
    recorded_at:    str    # ISO 8601
    last_verified:  str    # ISO 8601
    success_rate:   float  # 0.0–1.0
    schema_version: int    = field(default=SCHEMA_VERSION, init=False)

    def __post_init__(self) -> None:
        if not self.sop_id:
            raise ValueError("SOP.sop_id must not be empty")
        if not self.site_url:
            raise ValueError("SOP.site_url must not be empty")
        if not self.steps:
            raise ValueError("SOP.steps must not be empty")
        if not isinstance(self.steps, tuple):
            raise TypeError(f"SOP.steps must be a tuple, got {type(self.steps).__name__}")
        if not 0.0 <= self.success_rate <= 1.0:
            raise ValueError(f"SOP.success_rate must be 0.0–1.0, got {self.success_rate}")
        indices = [s.step_index for s in self.steps]
        if indices != list(range(len(self.steps))):
            raise ValueError(f"SOP steps must have contiguous 0-based indices, got {indices}")
        object.__setattr__(self, "schema_version", SCHEMA_VERSION)


@dataclass(frozen=True)
class Profile:
    """
    Frozen personality kernel for one candidate.
    Generated once. Never mutated after creation.
    Runtime answer generation receives this entire object — Claude
    interprets it, never invents personality ad-hoc.
    """
    profile_id:       str
    name:             str
    big_five:         BigFive
    response_bias:    ResponseBias
    linguistic_traits: LinguisticTraits
    behavior:         BehaviorFingerprint
    created_at:       str    # ISO 8601
    runs:             int    # >= 0, incremented by persistence layer only
    schema_version:   int    = field(default=SCHEMA_VERSION, init=False)

    def __post_init__(self) -> None:
        if not self.profile_id:
            raise ValueError("Profile.profile_id must not be empty")
        if not self.name:
            raise ValueError("Profile.name must not be empty")
        if self.runs < 0:
            raise ValueError(f"Profile.runs must be >= 0, got {self.runs}")
        object.__setattr__(self, "schema_version", SCHEMA_VERSION)
