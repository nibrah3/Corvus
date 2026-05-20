# fsm.py — Phase 7: Assessment State Machine
# SCHEMA_VERSION: 1
#
# Single responsibility: own and enforce FSM state transitions for one
# assessment run. Records history, fires listeners, checkpoints to JSON.
#
# The transition table in states.py is the ONLY authority — this file
# enforces it but never overrides it.
#
# MUST NOT: capture pixels, run OCR, execute actions, call LLMs.

from __future__ import annotations

import json
import time
from dataclasses import dataclass
from typing import Any, Callable, Optional

from .errors import ErrorCode, StateError
from .states import (
    TERMINAL_STATES,
    assert_valid_transition,
    is_valid_transition,
    reachable_from,
)
from .types import FSMState

FSM_VERSION: int = 1


# ── FSMTransition ─────────────────────────────────────────────────────────────

@dataclass(frozen=True)
class FSMTransition:
    """
    Record of a single state transition.

    from_state: the state before the transition.
    to_state:   the state after.
    timestamp:  time.monotonic() at moment of transition.
    reason:     short human-readable explanation (never empty in production).
    """
    from_state: FSMState
    to_state:   FSMState
    timestamp:  float
    reason:     str

    def __post_init__(self) -> None:
        if self.timestamp <= 0:
            raise ValueError(f"FSMTransition.timestamp must be > 0, got {self.timestamp}")


# ── AssessmentFSM ─────────────────────────────────────────────────────────────

class AssessmentFSM:
    """
    State machine for one assessment execution run.

    The FSM is the single source of truth for what the system is doing.
    All layers query it; none bypass it.

    Lifecycle:
        fsm = AssessmentFSM(profile_id="p1")
        fsm.transition(FSMState.NAVIGATE, "starting assessment")
        ...
        assert fsm.is_terminal()

    Checkpoint/restore:
        data = fsm.checkpoint()
        restored = AssessmentFSM.from_checkpoint(data)

    Listeners:
        fsm.add_listener(lambda t: print(t.to_state))
    """

    def __init__(self, profile_id: str) -> None:
        if not profile_id:
            raise ValueError("AssessmentFSM.profile_id must not be empty")
        self._state: FSMState = FSMState.INIT
        self._profile_id: str = profile_id
        self._history: list[FSMTransition] = []
        self._context: dict[str, Any] = {}
        self._listeners: list[Callable[[FSMTransition], None]] = []

    # ── State access ──────────────────────────────────────────────────────────

    @property
    def state(self) -> FSMState:
        return self._state

    @property
    def profile_id(self) -> str:
        return self._profile_id

    @property
    def history(self) -> tuple[FSMTransition, ...]:
        return tuple(self._history)

    def is_terminal(self) -> bool:
        return self._state in TERMINAL_STATES

    def can_transition_to(self, to: FSMState) -> bool:
        return is_valid_transition(self._state, to)

    def reachable(self) -> frozenset:
        return reachable_from(self._state)

    # ── Transitions ───────────────────────────────────────────────────────────

    def transition(self, to: FSMState, reason: str = "") -> None:
        """
        Execute a state transition.

        Validates against states.py table; raises StateError(E401) if invalid.
        Records transition in history. Fires all registered listeners.
        Listener exceptions are suppressed — they must never crash the FSM.
        """
        assert_valid_transition(self._state, to)
        t = FSMTransition(
            from_state=self._state,
            to_state=to,
            timestamp=time.monotonic(),
            reason=reason,
        )
        self._state = to
        self._history.append(t)
        for fn in self._listeners:
            try:
                fn(t)
            except Exception:
                pass

    def to_error(self, reason: str) -> None:
        """Convenience: transition to ERROR. No-op if already in ERROR."""
        if self._state != FSMState.ERROR:
            self.transition(FSMState.ERROR, reason=reason)

    def recover(self) -> None:
        """
        Recover from ERROR state back to NAVIGATE.
        Raises StateError if not currently in ERROR.
        """
        if self._state != FSMState.ERROR:
            raise StateError(
                ErrorCode.STATE_INVALID_TRANSITION,
                f"recover() called from non-ERROR state: {self._state.value}",
                {"current": self._state.value},
            )
        self.transition(FSMState.NAVIGATE, "error recovery")

    # ── Context ───────────────────────────────────────────────────────────────

    def set_context(self, key: str, value: Any) -> None:
        """Store a value in the run context. Survives state transitions."""
        self._context[key] = value

    def get_context(self, key: str, default: Any = None) -> Any:
        return self._context.get(key, default)

    def clear_context(self, key: str) -> None:
        self._context.pop(key, None)

    # ── Listeners ─────────────────────────────────────────────────────────────

    def add_listener(self, fn: Callable[[FSMTransition], None]) -> None:
        """Register a callback fired on every transition. Must not raise."""
        self._listeners.append(fn)

    def remove_listener(self, fn: Callable[[FSMTransition], None]) -> None:
        self._listeners = [f for f in self._listeners if f is not fn]

    # ── Checkpoint / restore ──────────────────────────────────────────────────

    def checkpoint(self) -> dict:
        """
        Return a JSON-serializable snapshot of this FSM.
        Listeners are NOT checkpointed — re-register them after restore().
        Context values that are not JSON-serializable are silently skipped.
        """
        safe_context: dict = {}
        for k, v in self._context.items():
            try:
                json.dumps(v)
                safe_context[k] = v
            except (TypeError, ValueError):
                pass

        return {
            "version": FSM_VERSION,
            "profile_id": self._profile_id,
            "state": self._state.value,
            "context": safe_context,
            "history": [
                {
                    "from":      t.from_state.value,
                    "to":        t.to_state.value,
                    "timestamp": t.timestamp,
                    "reason":    t.reason,
                }
                for t in self._history
            ],
        }

    @classmethod
    def from_checkpoint(cls, data: dict) -> "AssessmentFSM":
        """
        Restore an AssessmentFSM from a checkpoint dict.

        Raises SchemaError if version mismatch or required fields missing.
        """
        from .errors import SchemaError

        version = data.get("version")
        if version != FSM_VERSION:
            raise SchemaError(
                ErrorCode.SCHEMA_VERSION_MISMATCH,
                f"FSM checkpoint version {version!r} != current {FSM_VERSION}",
                {"got": version, "expected": FSM_VERSION},
            )

        instance = cls.__new__(cls)
        instance._profile_id = data["profile_id"]
        instance._state = FSMState(data["state"])
        instance._context = dict(data.get("context", {}))
        instance._listeners = []
        instance._history = [
            FSMTransition(
                from_state=FSMState(t["from"]),
                to_state=FSMState(t["to"]),
                timestamp=float(t["timestamp"]),
                reason=t["reason"],
            )
            for t in data.get("history", [])
        ]
        return instance

    # ── Diagnostics ───────────────────────────────────────────────────────────

    def __repr__(self) -> str:
        return (
            f"AssessmentFSM(state={self._state.value!r}, "
            f"profile_id={self._profile_id!r}, "
            f"transitions={len(self._history)})"
        )
