# events.py — Event type definitions for CareerBridge
# EVENTS_VERSION: 1
#
# Events are the ONLY communication mechanism between layers.
# No layer calls another layer directly — it emits an event.
# The state machine listens for events and drives transitions.
#
# Rule: every event carries a timestamp and source layer name.
# Rule: payload is read-only (MappingProxyType) after construction.

from __future__ import annotations

import time
import types as _types
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Optional


class EventType(Enum):
    # Capture layer emits
    FRAME_CAPTURED          = "frame_captured"
    FRAME_CHANGED           = "frame_changed"        # dirty region detected
    FRAME_STABLE            = "frame_stable"         # no change for N ms

    # Perception layer emits
    UIA_COMPLETE            = "uia_complete"
    OCR_COMPLETE            = "ocr_complete"
    UI_ELEMENT_DETECTED     = "ui_element_detected"
    POPUP_DETECTED          = "popup_detected"
    QUESTION_BLOCK_DETECTED = "question_block_detected"
    PAGE_LOADED             = "page_loaded"
    PERCEPTION_FAILED       = "perception_failed"

    # Action layer emits
    ACTION_DISPATCHED       = "action_dispatched"
    ACTION_VERIFIED         = "action_verified"
    ACTION_FAILED           = "action_failed"

    # State machine emits
    STATE_TRANSITION        = "state_transition"
    TIMEOUT                 = "timeout"

    # Reasoning layer emits
    LLM_RESPONSE_READY      = "llm_response_ready"

    # Persistence layer emits
    PROFILE_LOADED          = "profile_loaded"
    SOP_LOADED              = "sop_loaded"
    SOP_RECORDED            = "sop_recorded"

    # System events
    ASSESSMENT_COMPLETE     = "assessment_complete"
    ERROR                   = "error"


# Canonical source layer names — only these strings are valid as Event.source
SOURCE_CAPTURE     = "capture"
SOURCE_PERCEPTION  = "perception"
SOURCE_ACTION      = "action"
SOURCE_FSM         = "fsm"
SOURCE_REASONING   = "reasoning"
SOURCE_PERSISTENCE = "persistence"
SOURCE_SYSTEM      = "system"

_VALID_SOURCES = frozenset({
    SOURCE_CAPTURE, SOURCE_PERCEPTION, SOURCE_ACTION,
    SOURCE_FSM, SOURCE_REASONING, SOURCE_PERSISTENCE, SOURCE_SYSTEM,
})


@dataclass
class Event:
    """
    Immutable event emitted by one layer, consumed by the state machine.
    payload is frozen to MappingProxyType after construction.
    """
    event_type: EventType
    source:     str              # must be one of the SOURCE_* constants
    payload:    dict[str, Any]
    frame_id:   Optional[int]  = None
    timestamp:  float          = field(default_factory=time.monotonic)

    def __post_init__(self) -> None:
        if self.source not in _VALID_SOURCES:
            raise ValueError(
                f"Event.source must be one of {sorted(_VALID_SOURCES)}, got {self.source!r}"
            )
        if self.timestamp <= 0:
            raise ValueError(f"Event.timestamp must be > 0, got {self.timestamp}")
        if self.frame_id is not None and self.frame_id < 0:
            raise ValueError(f"Event.frame_id must be >= 0, got {self.frame_id}")
        self.payload = _types.MappingProxyType(self.payload)
