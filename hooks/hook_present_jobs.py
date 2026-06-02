#!/usr/bin/env python3
"""
hook_present_jobs.py — PostToolUse hook (Module 2)
Fires after mcp__vps__get_pending_approvals or mcp__vps__list_jobs.
Injects a formatted job list so Claude presents cards one at a time.
Never blocks — always exits 0.
"""
import io
import json
import sys

# Force UTF-8 stdout so hook output is never mangled by Windows console encoding
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

MAX_JOBS = 8


def fmt_score(score):
    if score is None:
        return ""
    try:
        return f"{int(float(score))}% match"
    except (ValueError, TypeError):
        return ""


def fmt_job(idx, j):
    job_id      = j.get("id") or j.get("job_id", "?")
    title       = (j.get("title") or "Untitled Role").strip()
    company     = (j.get("company") or "Unknown Company").strip()
    sector      = (j.get("sector") or "General").strip()
    score       = fmt_score(j.get("score"))
    source_url  = j.get("url") or ""
    official    = j.get("official_url") or ""
    quality     = j.get("quality_issue") or ""
    desc_field  = j.get("official_description") or j.get("description") or ""
    preview     = desc_field[:150].replace("\n", " ").strip()

    score_part   = f" | {score}" if score else ""
    primary_url  = official if official else source_url
    quality_note = ""
    if quality == "no_official_url":
        quality_note = "\n   [!] Official employer URL not confirmed — verify before applying"
    elif quality == "platform_scrape_failed":
        quality_note = "\n   [!] Could not retrieve full job details — source URL only"
    elif not official and not quality:
        quality_note = "\n   [enriching...] Official URL pending — check back shortly"

    url_line = f"   official_url={primary_url!r}"
    if official and source_url and source_url != official:
        url_line += f"\n   source_url={source_url!r}"

    return (
        f"{idx}. job_id={job_id} | \"{title}\" | company=\"{company}\""
        f" | sector=\"{sector}\"{score_part}\n"
        f"{url_line}"
        f"{quality_note}\n"
        f"   preview={preview!r}"
    )


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

    jobs = (
        tool_response.get("jobs")
        or tool_response.get("pending_approvals")
        or []
    )

    if not isinstance(jobs, list):
        jobs = []

    if not jobs:
        print(
            "[JOBS RESULT - EMPTY]\n"
            "No jobs found right now. Tell the user warmly: "
            "\"Nothing new at the moment - I'll keep an eye out for you.\" "
            "Then immediately show the Jobs & Assessments sub-menu via AskUserQuestion."
        )
        sys.exit(0)

    shown = min(len(jobs), MAX_JOBS)
    total = len(jobs)
    lines = [fmt_job(i + 1, j) for i, j in enumerate(jobs[:MAX_JOBS])]

    output = (
        f"[JOBS READY — showing {shown} of {total}]\n"
        "Present these jobs as AskUserQuestion cards ONE AT A TIME, starting with job #1.\n"
        "Card format:\n"
        "  question: \"[Job Title] at [Company]\"\n"
        "  header:   \"[sector] · [score]\"\n"
        "  options:  [Apply] [Skip] [More Info] [Back to Jobs]\n\n"
        "Button rules:\n"
        "  Apply        -> follow the Apply Flow in CLAUDE.md (use official_url as the assessment URL)\n"
        "  Skip         -> call mcp__vps__skip_job(job_id=<id>), then show next card\n"
        "  More Info    -> show official_url + preview text, then re-present the same card\n"
        "  Back to Jobs -> show Jobs & Assessments sub-menu via AskUserQuestion\n\n"
        "QUALITY NOTES:\n"
        "  - If a job shows [!] quality warning, include it in the card description text (warm, not alarming)\n"
        "  - If 'enriching...' tag: tell user 'Still confirming the official link — you can apply now or wait a moment'\n"
        "  - Always use official_url as the primary link. Use source_url only as a fallback if official_url is absent.\n"
        "After last job is applied/skipped → show Jobs & Assessments sub-menu.\n\n"
        "Jobs:\n" + "\n".join(lines)
    )

    print(output)
    sys.exit(0)


if __name__ == "__main__":
    main()
