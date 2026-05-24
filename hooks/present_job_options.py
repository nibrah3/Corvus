"""
present_job_options.py — PostToolUse hook for list_jobs, get_pending_approvals,
                         list_schools (and sqlite read_query results).

Injects a SYSTEM REMINDER telling Claude to present each result via
AskUserQuestion with the correct action options before doing anything else.
Also warns about any social media URLs that slipped through.
"""
import json
import sys

BLOCKED_DOMAINS = {
    "facebook.com", "fb.com", "instagram.com", "twitter.com",
    "x.com", "tiktok.com", "linkedin.com", "tiktok.com", "snapchat.com",
}

JOB_OPTIONS    = "[✅ Apply] [⏭ Skip] [ℹ More Info] [🔗 Open Job Page]"
SCHOOL_OPTIONS = "[ℹ More Info] [🌐 Open Enrollment Page] [⭐ Shortlist] [⏭ Skip]"


def _is_social(url: str) -> bool:
    url = (url or "").lower()
    return any(d in url for d in BLOCKED_DOMAINS)


def _format_job(j: dict, idx: int) -> str:
    title   = (j.get("title") or "Untitled")[:60]
    company = (j.get("company") or "Unknown")[:40]
    sector  = (j.get("sector") or "gig").upper()
    score   = j.get("score", "")
    score_s = f"  score={score:.2f}" if isinstance(score, float) else ""
    return f"  [{idx}] {title} — {company} ({sector}){score_s}"


def _format_school(s: dict, idx: int) -> str:
    name  = (s.get("name") or "Unknown")[:70]
    score = s.get("criteria_score", s.get("score", "?"))
    flags = []
    if s.get("no_id_verification"):     flags.append("No ID")
    if s.get("monthly_enrollment"):     flags.append("Monthly")
    if s.get("instant_acceptance"):     flags.append("Instant")
    if s.get("community_college"):      flags.append("Community")
    flag_s = "  [" + ", ".join(flags) + "]" if flags else ""
    return f"  [{idx}] {name} — {score}/6 criteria{flag_s}"


def main():
    try:
        ctx = json.loads(sys.stdin.read() or "{}")
    except Exception:
        sys.exit(0)

    tool_response = ctx.get("tool_response", {})
    tool_name     = ctx.get("tool_name", "")
    if not isinstance(tool_response, dict):
        sys.exit(0)

    # ── Jobs ──────────────────────────────────────────────────────────────────
    jobs = tool_response.get("jobs", [])
    if jobs:
        social = [j.get("url", "") for j in jobs if _is_social(j.get("url", ""))]
        lines  = [
            f"SYSTEM REMINDER: {len(jobs)} job(s) retrieved. "
            "Present EACH via AskUserQuestion before any other action.",
            f"Options per job: {JOB_OPTIONS}",
            "On [Apply]     → call mcp__vps__approve_job(job_id=N)",
            "On [Skip]      → call mcp__vps__skip_job(job_id=N)",
            "On [More Info] → call mcp__vps__get_job(job_id=N), show full description, re-present options",
            "On [Open Page] → call mcp__browser__navigate(url=job['url'])",
            "",
            "Jobs to present:",
        ]
        for i, j in enumerate(jobs, 1):
            lines.append(_format_job(j, i))
        if social:
            lines.append(f"\nWARNING: {len(social)} job(s) have social media URLs — skip them silently: {social[:2]}")
        print(json.dumps({"type": "system", "content": "\n".join(lines)}))
        sys.exit(0)

    # ── Schools ───────────────────────────────────────────────────────────────
    schools = tool_response.get("schools", [])
    if schools:
        lines = [
            f"SYSTEM REMINDER: {len(schools)} school(s) retrieved. "
            "Present EACH via AskUserQuestion before any other action.",
            f"Options per school: {SCHOOL_OPTIONS}",
            "On [More Info]         → show full evidence text and all criteria flags",
            "On [Open Enrollment]   → call mcp__browser__navigate(url=school['enrollment_url'])",
            "On [Shortlist]         → note it and continue to next",
            "On [Skip]              → move to next school",
            "",
            "Schools to present:",
        ]
        for i, s in enumerate(schools, 1):
            lines.append(_format_school(s, i))
        print(json.dumps({"type": "system", "content": "\n".join(lines)}))
        sys.exit(0)

    sys.exit(0)


if __name__ == "__main__":
    main()
