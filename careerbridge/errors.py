# errors.py — Error taxonomy for CareerBridge
# ERRORS_VERSION: 1
# No dependencies on other CareerBridge modules.
# Every error code maps to exactly one error class.
# Failure is a state, not an exception — all errors are caught and
# converted to FSM transitions in the orchestration layer.

from enum import Enum
from typing import Optional


class ErrorCode(Enum):
    # Capture errors (1xx)
    CAPTURE_WINDOW_NOT_FOUND    = "E101"
    CAPTURE_FRAME_TIMEOUT       = "E102"
    CAPTURE_INIT_FAILED         = "E103"

    # Perception errors (2xx)
    PERCEPTION_LOW_CONFIDENCE   = "E201"
    PERCEPTION_UIA_UNAVAILABLE  = "E202"
    PERCEPTION_NO_ELEMENTS      = "E203"
    PERCEPTION_TIMEOUT          = "E204"
    PERCEPTION_SHAPE_MISMATCH   = "E205"

    # Action errors (3xx)
    ACTION_TARGET_NOT_FOUND     = "E301"
    ACTION_CLICK_UNVERIFIED     = "E302"
    ACTION_TYPE_UNVERIFIED      = "E303"
    ACTION_SCROLL_UNVERIFIED    = "E304"
    ACTION_MAX_RETRIES          = "E305"

    # State machine errors (4xx)
    STATE_INVALID_TRANSITION    = "E401"
    STATE_CHECKPOINT_CORRUPT    = "E402"
    STATE_TIMEOUT               = "E403"

    # Persistence errors (5xx)
    PERSISTENCE_PROFILE_MISSING = "E501"
    PERSISTENCE_SOP_MISSING     = "E502"
    PERSISTENCE_WRITE_FAILED    = "E503"
    PERSISTENCE_SCHEMA_MISMATCH = "E504"

    # LLM errors (6xx)
    LLM_INVALID_RESPONSE        = "E601"
    LLM_TIMEOUT                 = "E602"
    LLM_RATE_LIMITED            = "E603"

    # SOP errors (7xx)
    SOP_ANCHOR_NOT_FOUND        = "E701"
    SOP_STEP_FAILED             = "E702"
    SOP_VERSION_MISMATCH        = "E703"

    # Profile errors (8xx)
    PROFILE_INVALID             = "E801"
    PROFILE_MISSING             = "E802"

    # Schema errors (9xx)
    SCHEMA_VERSION_MISMATCH     = "E901"
    SCHEMA_VALIDATION_FAILED    = "E902"


class CareerBridgeError(Exception):
    def __init__(self, code: ErrorCode, message: str, context: Optional[dict] = None):
        self.code = code
        self.context = context or {}
        super().__init__(f"[{code.value}] {message}")


class CaptureError(CareerBridgeError):     pass
class PerceptionError(CareerBridgeError):  pass
class ActionError(CareerBridgeError):      pass
class StateError(CareerBridgeError):       pass
class PersistenceError(CareerBridgeError): pass
class LLMError(CareerBridgeError):         pass
class SOPError(CareerBridgeError):         pass
class ProfileError(CareerBridgeError):     pass
class SchemaError(CareerBridgeError):      pass
