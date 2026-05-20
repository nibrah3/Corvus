# states.py — FSM formal specification for CareerBridge
# STATES_VERSION: 1
#
# This file is the single source of truth for state machine transitions.
# No execution logic lives here — only the transition contract.
# The FSM implementation (fsm.py) must import and enforce this table.
#
# Changing this table is a breaking change — version bump required.

from __future__ import annotations

from typing import FrozenSet

from .errors import ErrorCode, StateError
from .types import FSMState

STATES_VERSION: int = 1

# Formal transition table: state → frozenset of valid next states
VALID_TRANSITIONS: dict[FSMState, FrozenSet[FSMState]] = {
    FSMState.INIT:     frozenset({FSMState.NAVIGATE, FSMState.ERROR}),
    FSMState.NAVIGATE: frozenset({FSMState.WAIT_UI,  FSMState.ERROR}),
    FSMState.WAIT_UI:  frozenset({FSMState.EXTRACT,  FSMState.NAVIGATE, FSMState.ERROR}),
    FSMState.EXTRACT:  frozenset({FSMState.REASON,   FSMState.ERROR}),
    FSMState.REASON:   frozenset({FSMState.EXECUTE,  FSMState.ERROR}),
    FSMState.EXECUTE:  frozenset({FSMState.VERIFY,   FSMState.ERROR}),
    FSMState.VERIFY:   frozenset({FSMState.EXECUTE,  FSMState.NAVIGATE, FSMState.COMPLETE, FSMState.ERROR}),
    FSMState.COMPLETE: frozenset(),           # terminal — no outbound transitions
    FSMState.ERROR:    frozenset({FSMState.NAVIGATE}),  # single recovery path only
}

TERMINAL_STATES: FrozenSet[FSMState] = frozenset({FSMState.COMPLETE, FSMState.ERROR})

# States where the action layer is allowed to execute
EXECUTION_STATES: FrozenSet[FSMState] = frozenset({FSMState.EXECUTE})

# States where LLM calls are allowed
REASONING_STATES: FrozenSet[FSMState] = frozenset({FSMState.REASON})

# States where perception is allowed to run
PERCEPTION_STATES: FrozenSet[FSMState] = frozenset({FSMState.WAIT_UI, FSMState.EXTRACT})


def is_valid_transition(from_state: FSMState, to_state: FSMState) -> bool:
    return to_state in VALID_TRANSITIONS.get(from_state, frozenset())


def assert_valid_transition(from_state: FSMState, to_state: FSMState) -> None:
    if not is_valid_transition(from_state, to_state):
        raise StateError(
            ErrorCode.STATE_INVALID_TRANSITION,
            f"Invalid transition: {from_state.value} → {to_state.value}",
            {"from": from_state.value, "to": to_state.value},
        )


def all_states() -> tuple[FSMState, ...]:
    return tuple(FSMState)


def reachable_from(state: FSMState) -> FrozenSet[FSMState]:
    return VALID_TRANSITIONS.get(state, frozenset())
