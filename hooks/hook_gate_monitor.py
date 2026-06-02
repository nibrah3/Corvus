#!/usr/bin/env python3
"""
hook_gate_monitor.py — UserPromptSubmit hook (Module 3, supervised mode).
Checks Redis for pending assessment gates. If one is waiting, injects
a mandatory instruction for Claude to surface it as an AskUserQuestion.
Only fires when the pipeline is actually blocked — no noise in normal operation.
"""
import io
import json
import sys

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

REDIS_HOST = "localhost"
REDIS_PORT = 6380       # SSH tunnel port
GATE_KEY   = "corvus:pending_gates"


def _peek_gate() -> dict | None:
    try:
        import redis
        r = redis.Redis(host=REDIS_HOST, port=REDIS_PORT,
                        decode_responses=True, socket_connect_timeout=2)
        raw = r.lindex(GATE_KEY, 0)
        return json.loads(raw) if raw else None
    except Exception:
        return None


def main():
    try:
        sys.stdin.buffer.read()
    except Exception:
        pass

    gate = _peek_gate()
    if not gate:
        sys.exit(0)

    gate_id = gate.get("gate_id", "unknown")
    field   = gate.get("field", "a question")
    draft   = (gate.get("draft") or "").strip()
    draft_display = f'"{draft[:120]}"' if draft else "(no draft generated)"

    output = (
        f"[SUPERVISED GATE - ASSESSMENT PAUSED]\n"
        f"The assessment is waiting for your input before it can continue.\n"
        f"gate_id={gate_id}\n\n"
        f"Question/field: \"{field}\"\n"
        f"Prepared answer: {draft_display}\n\n"
        f"You MUST call AskUserQuestion immediately with:\n"
        f"  question: \"How should I answer: '{field[:80]}'?\"\n"
        f"  header: \"Review Answer\"\n"
        f"  options:\n"
        f"    - label: \"Approve\"  description: \"Use the prepared answer as-is\"\n"
        f"    - label: \"Edit\"     description: \"I'll provide a different answer\"\n"
        f"    - label: \"Skip\"     description: \"Leave this field blank and continue\"\n\n"
        f"After the user decides:\n"
        f"  Approve -> run: C:\\Python314\\python.exe D:\\cb-core\\hooks\\answer_gate.py "
        f"{gate_id} approve\n"
        f"  Edit    -> ask user for the text, then run: "
        f"C:\\Python314\\python.exe D:\\cb-core\\hooks\\answer_gate.py {gate_id} edit <text>\n"
        f"  Skip    -> run: C:\\Python314\\python.exe D:\\cb-core\\hooks\\answer_gate.py "
        f"{gate_id} skip\n"
    )

    print(output)
    sys.exit(0)


if __name__ == "__main__":
    main()
