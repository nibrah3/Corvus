"""
schools_filter.py — PreToolUse hook for mcp__schools__send_school_reports
                    and mcp__schools__list_confirmed_schools.

If the tool is called without any filters specified, this hook blocks the call
and injects a SYSTEM REMINDER instructing Claude to present an AskUserQuestion
filter-selection UI before proceeding.
"""
import json
import sys


def main():
    try:
        ctx = json.loads(sys.stdin.read() or "{}")
    except Exception:
        sys.exit(0)

    args = ctx.get("tool_input", {}) or {}
    filters = args.get("filters")

    # Pass through if filters already supplied and non-empty
    if filters and isinstance(filters, list) and len(filters) > 0:
        sys.exit(0)

    # Also pass through if caller explicitly passed empty list to mean "all"
    # and min_score is set above default — they know what they want
    min_score = args.get("min_score", 1)
    if isinstance(filters, list) and len(filters) == 0 and min_score > 1:
        sys.exit(0)

    # Block and instruct Claude to ask the user first
    reminder = (
        "SYSTEM REMINDER: Before browsing or sending school reports, "
        "present the user with the school filter selection UI using AskUserQuestion.\n\n"
        "Call AskUserQuestion with EXACTLY these two questions:\n\n"
        "─── Question 1 ───\n"
        "  question:     'Which school criteria are you looking for?'\n"
        "  header:       'School Criteria'\n"
        "  multiSelect:  true\n"
        "  options:\n"
        "    • label='Community College'        description='Two-year community or junior colleges'\n"
        "    • label='No ID Verification'       description='Can enroll without government-issued ID'\n"
        "    • label='No Transcript Required'   description='No prior academic records needed'\n"
        "    • label='Monthly Enrollment'       description='Rolling or monthly start dates — start anytime'\n"
        "    • label='Instant Acceptance'       description='Same-day or immediate application decision'\n"
        "    • label='Monthly Refund'           description='Pro-rated monthly tuition refund policy'\n\n"
        "─── Question 2 ───\n"
        "  question:    'Describe anything specific you are looking for (optional):'\n"
        "  header:      'Custom'\n"
        "  multiSelect: false\n"
        "  options:\n"
        "    • label='No specific requirement'  description='Show top-scoring schools for selected criteria'\n"
        "    • label='Other'                    description='Type your own description'\n\n"
        "After receiving the user's answers:\n"
        "  1. Map selected labels to these filter keys:\n"
        "       Community College        → community_college\n"
        "       No ID Verification       → no_id_verification\n"
        "       No Transcript Required   → no_transcript_required\n"
        "       Monthly Enrollment       → monthly_enrollment\n"
        "       Instant Acceptance       → instant_acceptance\n"
        "       Monthly Refund           → monthly_refund\n"
        "  2. If the user provided custom text (not 'No specific requirement'),\n"
        "     pass it as the custom_query parameter.\n"
        "  3. Call mcp__schools__send_school_reports(\n"
        "         filters=[...mapped keys...],\n"
        "         custom_query='...user text or empty...',\n"
        "         min_score=1,\n"
        "         limit=20\n"
        "     )\n"
        "  4. Do NOT retry the original blocked tool call."
    )

    print(json.dumps({"type": "system", "content": reminder}))
    sys.exit(2)


if __name__ == "__main__":
    main()
