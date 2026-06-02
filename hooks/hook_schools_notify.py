#!/usr/bin/env python3
"""
hook_schools_notify.py — PostToolUse hook (Module 4)
Fires after:
  - mcp__schools__discover_schools    -> acknowledge start, show sub-menu
  - mcp__schools__send_school_reports -> confirm how many PDFs were sent
Never blocks — always exits 0.
"""
import io
import json
import sys

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

CRITERIA_LABELS = {
    "community_college":      "Community College",
    "no_id_verification":     "No ID required",
    "no_transcript_required": "No transcripts needed",
    "monthly_enrollment":     "Monthly start dates",
    "instant_acceptance":     "Instant acceptance",
    "monthly_refund":         "Monthly refund policy",
}


def handle_discover(tool_response: dict) -> None:
    job_id = tool_response.get("job_id", "")
    error  = tool_response.get("error", "")

    if error:
        print(
            "[DISCOVERY ERROR]\n"
            f"Discovery could not start: {error}\n"
            "Tell the user warmly and show the Schools sub-menu."
        )
        return

    print(
        "[DISCOVERY STARTED]\n"
        f"job_id={job_id}\n"
        "Tell the user: \"I've started searching for schools — "
        "I'll send the results straight to your phone when I'm done. "
        "This usually takes a few minutes.\"\n"
        "Then immediately show the Schools sub-menu via AskUserQuestion.\n"
        "Do NOT poll get_discovery_status unless the user explicitly asks for a progress update."
    )


def handle_reports(tool_input: dict, tool_response: dict) -> None:
    sent    = tool_response.get("sent", 0)
    failed  = tool_response.get("failed", 0)
    matched = tool_response.get("matched", 0)
    filters = tool_response.get("filters") or tool_input.get("filters") or []

    criteria = [CRITERIA_LABELS.get(f, f) for f in filters if f in CRITERIA_LABELS]
    criteria_str = ", ".join(criteria) if criteria else "all schools"

    if matched == 0:
        print(
            "[REPORTS - NO MATCHES]\n"
            f"No schools matched the selected criteria ({criteria_str}).\n"
            "Tell the user: \"I couldn't find any schools matching that combination "
            "- try a broader search or run Discover Schools again.\"\n"
            "Then show the Schools sub-menu."
        )
        return

    if sent == 0 and failed > 0:
        print(
            "[REPORTS - SEND FAILED]\n"
            f"Found {matched} school(s) but failed to send the reports.\n"
            "Tell the user: \"I found schools but ran into trouble sending them — "
            "let me try again in a moment.\"\n"
            "Then show the Schools sub-menu."
        )
        return

    print(
        f"[REPORTS SENT]\n"
        f"sent={sent}  failed={failed}  matched={matched}\n"
        f"criteria={criteria_str}\n"
        f"Tell the user: \"Done! I sent {sent} school report{'s' if sent != 1 else ''} "
        f"to your phone. Filter: {criteria_str}.\"\n"
        "Then show the Schools sub-menu via AskUserQuestion."
    )


def main():
    try:
        raw = sys.stdin.buffer.read().decode("utf-8-sig", errors="replace")
        ctx = json.loads(raw) if raw.strip() else {}
    except Exception:
        sys.exit(0)

    tool_name     = ctx.get("tool_name", "")
    tool_input    = ctx.get("tool_input", {}) or {}
    tool_response = ctx.get("tool_response", {})

    if isinstance(tool_response, str):
        try:
            tool_response = json.loads(tool_response)
        except Exception:
            tool_response = {}
    if not isinstance(tool_response, dict):
        tool_response = {}

    if "discover_schools" in tool_name:
        handle_discover(tool_response)
    elif "send_school_reports" in tool_name:
        handle_reports(tool_input, tool_response)

    sys.exit(0)


if __name__ == "__main__":
    main()
