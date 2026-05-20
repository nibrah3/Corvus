#!/usr/bin/env python3
# run_assessment.py — CLI entry point for one assessment execution.
# SCHEMA_VERSION: 1
#
# Reads JSON payload from stdin (or --input flag).
# Writes JSON result to stdout.
# Exit code 0 always — errors are reported inside the result JSON.
#
# Input contract:
#   {
#     "profile":      {...},       # required — Profile dict
#     "sop":          {...}|null,  # null → discovery mode
#     "url":          "https://...",
#     "goal":         "Complete the assessment...",
#     "window_title": "IXBrowser"  # optional, default "IXBrowser"
#   }
#
# Output contract:
#   {
#     "run_id":      "uuid",
#     "mode":        "discovery" | "execution",
#     "profile_id":  "...",
#     "site_url":    "...",
#     "final_state": "complete" | "error" | ...,
#     "elapsed_s":   45.2,
#     "updated_sop": null,         # SOP recording: future enhancement
#     "fsm_history": [...],
#     "error":       null | "...", # last ERROR transition reason if applicable
#     "started_at":  "ISO8601",
#     "completed_at":"ISO8601"
#   }

from __future__ import annotations

import argparse
import datetime
import json
import os
import sys
import time
import uuid

# Make the package importable when invoked directly.
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# Load OPENROUTER_API_KEY from the shared runtime .env if not already in env.
_ENV_FILE = r"E:\careerbridge\runtime\.env"
if not os.getenv("OPENROUTER_API_KEY") and os.path.exists(_ENV_FILE):
    with open(_ENV_FILE, encoding="utf-8") as _f:
        for _line in _f:
            _line = _line.strip()
            if _line.startswith("OPENROUTER_API_KEY=") and "=" in _line:
                os.environ["OPENROUTER_API_KEY"] = _line.split("=", 1)[1].strip()
                break

from careerbridge.navigator import make_navigator
from careerbridge.orchestrator import AssessmentOrchestrator
from careerbridge.persistence import (
    profile_from_dict,
    result_to_dict,
    sop_from_dict,
)
from careerbridge.reasoning.claude_reasoner import claude_reasoner


def _now() -> str:
    return datetime.datetime.now(datetime.timezone.utc).isoformat()


def _error_from_history(history: list[dict]) -> str | None:
    for entry in reversed(history):
        if entry["to"] == "error":
            return entry["reason"]
    return None


def run(payload: dict) -> dict:
    run_id     = str(uuid.uuid4())
    started_at = _now()
    t0         = time.monotonic()

    profile      = profile_from_dict(payload["profile"])
    sop_dict     = payload.get("sop")
    sop          = sop_from_dict(sop_dict) if sop_dict else None
    site_url     = payload["url"]
    window_title = payload.get("window_title", "IXBrowser")
    mode         = "discovery" if sop is None else "execution"
    navigator    = make_navigator(window_title) if sop is not None else None

    orch = AssessmentOrchestrator(
        window_title=window_title,
        profile=profile,
        sop=sop,
        reasoner=claude_reasoner,
        navigator=navigator,
    )

    final_state = orch.run()
    elapsed_s   = round(time.monotonic() - t0, 3)
    history     = orch.fsm.checkpoint()["history"]
    error       = _error_from_history(history) if final_state.value == "error" else None

    return result_to_dict(
        run_id=run_id,
        mode=mode,
        profile_id=profile.profile_id,
        site_url=site_url,
        final_state=final_state.value,
        elapsed_s=elapsed_s,
        fsm_history=history,
        error=error,
        started_at=started_at,
        completed_at=_now(),
    )


def main() -> None:
    parser = argparse.ArgumentParser(description="Run one CareerBridge assessment.")
    group = parser.add_mutually_exclusive_group()
    group.add_argument("--input", "-i", default=None,
                       help="JSON payload as a string literal.")
    group.add_argument("--input-file", "-f", default=None,
                       help="Path to a JSON file containing the payload.")
    args = parser.parse_args()

    if args.input is not None:
        raw = args.input
    elif args.input_file is not None:
        with open(args.input_file, encoding="utf-8") as fh:
            raw = fh.read()
    else:
        raw = sys.stdin.read()

    try:
        payload = json.loads(raw)
    except json.JSONDecodeError as exc:
        json.dump({"error": f"invalid JSON input: {exc}", "final_state": "error"}, sys.stdout)
        sys.stdout.write("\n")
        sys.exit(0)

    result = run(payload)
    json.dump(result, sys.stdout, indent=2)
    sys.stdout.write("\n")


if __name__ == "__main__":
    main()
