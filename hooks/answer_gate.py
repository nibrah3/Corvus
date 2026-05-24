"""
answer_gate.py — Claude Code calls this to respond to an assessment gate.

Usage:
    python D:\\cb-core\\hooks\\answer_gate.py <gate_id> approve
    python D:\\cb-core\\hooks\\answer_gate.py <gate_id> skip
    python D:\\cb-core\\hooks\\answer_gate.py <gate_id> edit "My edited answer text"

The assessment_pipeline.py subprocess is blocking on corvus:gate_response:{gate_id}.
This script writes the answer there, unblocking the pipeline.
"""
import json
import sys
import os

sys.path.insert(0, os.path.normpath(os.path.join(os.path.dirname(__file__), "..")))
from careerbridge.gate_client import answer_gate


def main():
    if len(sys.argv) < 3:
        print("Usage: answer_gate.py <gate_id> approve|skip|edit [answer_text]")
        sys.exit(1)

    gate_id = sys.argv[1]
    action  = sys.argv[2].lower()
    answer  = " ".join(sys.argv[3:]) if len(sys.argv) > 3 else ""

    if action not in ("approve", "skip", "edit"):
        print(f"Invalid action {action!r}. Use: approve | skip | edit")
        sys.exit(1)

    answer_gate(gate_id, action, answer)
    print(json.dumps({"ok": True, "gate_id": gate_id, "action": action}))


if __name__ == "__main__":
    main()
