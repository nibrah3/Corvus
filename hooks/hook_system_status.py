#!/usr/bin/env python3
"""
hook_system_status.py - PostToolUse hook (Module 6)
Fires after mcp__vps__get_system_status.
Formats the VPS-side health data (job counts, Redis, Postgres) so Claude
can merge it with the local port check (already in context from Bash).
Never blocks -- always exits 0.
"""
import io
import json
import sys

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")


def _status_word(val: str) -> str:
    return "connected" if val == "ok" else f"issue ({val})"


def main():
    try:
        raw = sys.stdin.buffer.read().decode("utf-8-sig", errors="replace")
        ctx = json.loads(raw) if raw.strip() else {}
    except Exception:
        sys.exit(0)

    tool_response = ctx.get("tool_response", {})
    if isinstance(tool_response, str):
        try:
            tool_response = json.loads(tool_response)
        except Exception:
            tool_response = {}
    if not isinstance(tool_response, dict):
        tool_response = {}

    if "error" in tool_response:
        print(
            "[VPS STATUS ERROR]\n"
            f"Could not reach VPS status check: {tool_response['error']}\n"
            "Tell the user: \"I couldn't reach the VPS right now - the tunnel may be down.\"\n"
            "Still report the local service status from the Bash output above.\n"
            "Then show the System sub-menu."
        )
        sys.exit(0)

    redis_ok    = tool_response.get("redis", "error") == "ok"
    postgres_ok = tool_response.get("postgres", "error") == "ok"
    pending     = tool_response.get("pending_approvals", 0)
    approved    = tool_response.get("approved_jobs", 0)
    by_status   = tool_response.get("jobs_by_status") or {}

    total_jobs = sum(by_status.values()) if by_status else 0

    redis_str    = "connected" if redis_ok    else "not reachable"
    postgres_str = "connected" if postgres_ok else "not reachable"

    jobs_lines = []
    for st, count in sorted(by_status.items()):
        jobs_lines.append(f"{count} {st}")
    jobs_str = ", ".join(jobs_lines) if jobs_lines else "no jobs on record"

    vps_health = "healthy" if (redis_ok and postgres_ok) else "degraded"

    print(
        f"[VPS STATUS]\n"
        f"vps_health={vps_health}  redis={redis_str}  postgres={postgres_str}\n"
        f"pending_approvals={pending}  approved_jobs={approved}  total_jobs={total_jobs}\n"
        f"jobs_by_status: {jobs_str}\n\n"
        "Combine this with the local port check above and give ONE plain-English summary:\n\n"
        "Template (adapt based on actual numbers):\n"
        "  \"[X] of [total] services are running. "
        "Your VPS connection is [healthy/having issues]. "
        "You have [N] job opportunities waiting to review.\"\n\n"
        "Then list only the OFFLINE services by name (skip the working ones).\n"
        "If everything is up: \"Everything looks great - all systems go!\"\n"
        "Then show the System sub-menu via AskUserQuestion."
    )
    sys.exit(0)


if __name__ == "__main__":
    main()
