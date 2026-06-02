#!/usr/bin/env python3
"""
hook_present_schools.py — PostToolUse hook (Module 4)
Fires after mcp__schools__list_confirmed_schools.
Formats school list so Claude presents cards one at a time.
Never blocks — always exits 0.
"""
import io
import json
import sys

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

MAX_SCHOOLS = 10

CRITERIA_LABELS = {
    "community_college":      "Community College",
    "no_id_verification":     "No ID required",
    "no_transcript_required": "No transcripts needed",
    "monthly_enrollment":     "Monthly start dates",
    "instant_acceptance":     "Instant acceptance",
    "monthly_refund":         "Monthly refund policy",
}


def fmt_school(idx: int, s: dict) -> str:
    name     = (s.get("name") or "Unknown School").strip()
    stype    = s.get("type") or ""
    city     = s.get("city") or ""
    state    = s.get("state") or ""
    score    = s.get("criteria_score", 0)
    filters  = s.get("filters") or []
    url      = s.get("url") or ""
    enroll   = s.get("enrollment_url") or ""

    location = ", ".join(p for p in [city, state] if p) or "Location unknown"
    met = [CRITERIA_LABELS.get(f, f) for f in filters if f in CRITERIA_LABELS]
    criteria_str = " | ".join(met) if met else "No criteria met"
    type_str = f" ({stype})" if stype else ""

    lines = [
        f"{idx}. \"{name}\"{type_str} — {location}",
        f"   Score: {score}/6  |  {criteria_str}",
        f"   url={url!r}",
    ]
    if enroll and enroll != url:
        lines.append(f"   enrollment_url={enroll!r}")
    return "\n".join(lines)


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

    if "error" in tool_response:
        print(
            "[SCHOOLS ERROR]\n"
            f"Could not load schools: {tool_response['error']}\n"
            "Tell the user warmly and show the Schools sub-menu."
        )
        sys.exit(0)

    schools = tool_response.get("schools") or []
    if not isinstance(schools, list):
        schools = []

    if not schools:
        print(
            "[SCHOOLS - NONE CONFIRMED YET]\n"
            "No confirmed schools found. Tell the user: "
            "\"Nothing lined up yet — run Discover Schools first and check back shortly.\"\n"
            "Then show the Schools sub-menu."
        )
        sys.exit(0)

    shown = min(len(schools), MAX_SCHOOLS)
    total = len(schools)
    lines = [fmt_school(i + 1, s) for i, s in enumerate(schools[:MAX_SCHOOLS])]

    output = (
        f"[SCHOOLS READY - {shown} of {total} confirmed]\n"
        "Present these schools ONE AT A TIME as AskUserQuestion cards, starting with school #1.\n\n"
        "Card format for each school:\n"
        "  question: \"[School Name] — [City, State]\"\n"
        "  header:   \"[type] - Score [X]/6\"\n"
        "  options:  [Send to my Phone] [Next School] [Back to Schools Menu]\n\n"
        "Button rules:\n"
        "  Send to my Phone   -> call mcp__schools__send_school_reports with the school's\n"
        "                        criteria filters list as the filters param, limit=1\n"
        "  Next School        -> present the next school card\n"
        "  Back to Schools Menu -> show the Schools sub-menu\n"
        "After last school: show the Schools sub-menu.\n\n"
        "Schools:\n" + "\n".join(lines)
    )

    print(output)
    sys.exit(0)


if __name__ == "__main__":
    main()
