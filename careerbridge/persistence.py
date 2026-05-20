# persistence.py — JSON serialization boundary for ZeroClaw memory I/O
# SCHEMA_VERSION: 1
#
# No database. No I/O. Pure dataclass ↔ dict conversion.
# Deserializes the skill's --input payload into domain objects.
# Serializes domain objects into dicts for the skill to memory_pin.

from __future__ import annotations

from typing import Any, Optional

from .schema import (
    BigFive,
    BehaviorFingerprint,
    LinguisticTraits,
    Profile,
    ResponseBias,
    SOP,
    SOPStep,
)
from .types import ActionType, MouseSpeed


# ── Profile ───────────────────────────────────────────────────────────────────

def profile_from_dict(d: dict[str, Any]) -> Profile:
    b   = d["big_five"]
    rb  = d["response_bias"]
    lt  = d["linguistic_traits"]
    beh = d["behavior"]
    return Profile(
        profile_id=d["profile_id"],
        name=d["name"],
        big_five=BigFive(
            openness=b["openness"],
            conscientiousness=b["conscientiousness"],
            extraversion=b["extraversion"],
            agreeableness=b["agreeableness"],
            neuroticism=b["neuroticism"],
        ),
        response_bias=ResponseBias(
            extreme_answer_rate=rb["extreme_answer_rate"],
            neutral_preference=rb["neutral_preference"],
            social_desirability_bias=rb["social_desirability_bias"],
            consistency_strength=rb["consistency_strength"],
        ),
        linguistic_traits=LinguisticTraits(
            verbosity=lt["verbosity"],
            formality=lt["formality"],
            optimism=lt["optimism"],
        ),
        behavior=BehaviorFingerprint(
            typing_wpm=beh["typing_wpm"],
            error_rate=beh["error_rate"],
            mouse_speed=MouseSpeed(beh["mouse_speed"]),
            pause_min_ms=beh["pause_min_ms"],
            pause_max_ms=beh["pause_max_ms"],
        ),
        created_at=d["created_at"],
        runs=d["runs"],
    )


def profile_to_dict(p: Profile) -> dict[str, Any]:
    return {
        "profile_id": p.profile_id,
        "name":       p.name,
        "big_five": {
            "openness":          p.big_five.openness,
            "conscientiousness": p.big_five.conscientiousness,
            "extraversion":      p.big_five.extraversion,
            "agreeableness":     p.big_five.agreeableness,
            "neuroticism":       p.big_five.neuroticism,
        },
        "response_bias": {
            "extreme_answer_rate":      p.response_bias.extreme_answer_rate,
            "neutral_preference":       p.response_bias.neutral_preference,
            "social_desirability_bias": p.response_bias.social_desirability_bias,
            "consistency_strength":     p.response_bias.consistency_strength,
        },
        "linguistic_traits": {
            "verbosity": p.linguistic_traits.verbosity,
            "formality":  p.linguistic_traits.formality,
            "optimism":   p.linguistic_traits.optimism,
        },
        "behavior": {
            "typing_wpm":   p.behavior.typing_wpm,
            "error_rate":   p.behavior.error_rate,
            "mouse_speed":  p.behavior.mouse_speed.value,
            "pause_min_ms": p.behavior.pause_min_ms,
            "pause_max_ms": p.behavior.pause_max_ms,
        },
        "created_at": p.created_at,
        "runs":       p.runs,
    }


# ── SOP ───────────────────────────────────────────────────────────────────────

def sop_from_dict(d: dict[str, Any]) -> SOP:
    steps = tuple(
        SOPStep(
            step_index=s["step_index"],
            action_type=ActionType(s["action_type"]),
            anchor_text=s["anchor_text"],
            wait_for=s["wait_for"],
            payload=dict(s.get("payload", {})),
        )
        for s in d["steps"]
    )
    return SOP(
        sop_id=d["sop_id"],
        site_url=d["site_url"],
        steps=steps,
        recorded_at=d["recorded_at"],
        last_verified=d["last_verified"],
        success_rate=d["success_rate"],
    )


def sop_to_dict(s: SOP) -> dict[str, Any]:
    return {
        "sop_id":        s.sop_id,
        "site_url":      s.site_url,
        "recorded_at":   s.recorded_at,
        "last_verified": s.last_verified,
        "success_rate":  s.success_rate,
        "steps": [
            {
                "step_index":  step.step_index,
                "action_type": step.action_type.value,
                "anchor_text": step.anchor_text,
                "wait_for":    step.wait_for,
                "payload":     dict(step.payload),
            }
            for step in s.steps
        ],
    }


# ── Result ────────────────────────────────────────────────────────────────────

def result_to_dict(
    run_id:       str,
    mode:         str,
    profile_id:   str,
    site_url:     str,
    final_state:  str,
    elapsed_s:    float,
    fsm_history:  list[dict],
    error:        Optional[str],
    started_at:   str,
    completed_at: str,
    updated_sop:  Optional[dict] = None,
) -> dict[str, Any]:
    return {
        "run_id":       run_id,
        "mode":         mode,
        "profile_id":   profile_id,
        "site_url":     site_url,
        "final_state":  final_state,
        "elapsed_s":    elapsed_s,
        "updated_sop":  updated_sop,
        "fsm_history":  fsm_history,
        "error":        error,
        "started_at":   started_at,
        "completed_at": completed_at,
    }
