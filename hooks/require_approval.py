"""
require_approval.py — PreToolUse hook.

Blocks Bash / humanizer / UIA tool calls unless the current job_id has been
explicitly approved via AskUserQuestion in this session.

Approval is recorded in E:\cb-core\.approval_state.json by the session logic
when Mike taps [Apply] on a job.

Exit codes:
  0 — proceed
  2 — block (Claude Code surfaces the message to the user)
"""
import json
import os
import sys

STATE_FILE = os.path.join(os.path.dirname(os.path.dirname(__file__)), ".approval_state.json")


def _load_state() -> dict:
    try:
        with open(STATE_FILE) as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return {}


def main():
    # Read the tool call context from stdin (Claude Code passes it as JSON)
    try:
        raw = sys.stdin.read()
        ctx = json.loads(raw) if raw.strip() else {}
    except Exception:
        ctx = {}

    tool_name = ctx.get("tool_name", "")
    tool_input = ctx.get("tool_input", {})

    # Only gate tools that automate the browser/UI
    gated_prefixes = ("mcp__humanizer__", "mcp__uia__", "mcp__capture__")
    if not any(tool_name.startswith(p) for p in gated_prefixes):
        sys.exit(0)

    state = _load_state()
    current_job_id = state.get("current_job_id")
    approved_ids   = set(state.get("approved_job_ids", []))

    if current_job_id and current_job_id not in approved_ids:
        msg = (
            f"Job {current_job_id} has not been approved via AskUserQuestion. "
            f"Present the job to Mike with [Apply][Skip][More Info] before running automation."
        )
        print(json.dumps({"type": "error", "content": msg}))
        sys.exit(2)

    sys.exit(0)


if __name__ == "__main__":
    main()
