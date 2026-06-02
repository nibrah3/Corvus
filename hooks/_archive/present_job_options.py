"""
present_job_options.py — PostToolUse hook for list_jobs, get_pending_approvals, list_schools.

For jobs:  filters to relevant types (AI/annotation/moderation/writing), then presents
           each with [Apply] [See Details] [Skip] [Open Page] buttons.
For schools: shows criteria badges, presents each with [Enroll] [See Details] [Shortlist] [Skip].
"""
import json
import sys

BLOCKED_DOMAINS = {
    "facebook.com", "fb.com", "instagram.com", "twitter.com",
    "x.com", "tiktok.com", "linkedin.com", "snapchat.com",
}

# Job types we care about — match against title + sector + description
RELEVANT_KEYWORDS = {
    "data annotation", "ai training", "rlhf", "reinforcement learning",
    "chat moderation", "content moderation", "transcription", "data labeling",
    "data collection", "image annotation", "text annotation", "video annotation",
    "quality assurance", "qa review", "writing", "content writing",
    "microtask", "gig", "online work", "earn", "survey", "testing",
    "freelance", "remote work", "task", "crowdsource", "label",
}

BLOCKED_JOB_KEYWORDS = {
    "sales", "real estate", "insurance agent", "multi-level", "mlm",
    "recruitment", "recruiter", "hr manager",
}


def _is_social(url: str) -> bool:
    url = (url or "").lower()
    return any(d in url for d in BLOCKED_DOMAINS)


def _is_relevant_job(j: dict) -> bool:
    text = " ".join([
        (j.get("title") or ""),
        (j.get("sector") or ""),
        (j.get("description") or "")[:300],
    ]).lower()
    if any(kw in text for kw in BLOCKED_JOB_KEYWORDS):
        return False
    if any(kw in text for kw in RELEVANT_KEYWORDS):
        return True
    return False


def _format_job(j: dict, idx: int) -> str:
    title   = (j.get("title") or "Untitled")[:55]
    company = (j.get("company") or "Unknown")[:35]
    sector  = (j.get("sector") or "gig").upper()
    score   = j.get("score", "")
    score_s = f"  [{score:.0%} match]" if isinstance(score, float) and score else ""
    return f"  [{idx}] {title} — {company} ({sector}){score_s}"


def _format_school(s: dict, idx: int) -> str:
    name  = (s.get("name") or "Unknown")[:65]
    flags = []
    if s.get("no_id_verification"):   flags.append("No ID")
    if s.get("no_transcript_required"): flags.append("No Transcript")
    if s.get("monthly_enrollment"):   flags.append("Monthly Start")
    if s.get("instant_acceptance"):   flags.append("Instant Accept")
    if s.get("monthly_refund"):       flags.append("Monthly Refund")
    if s.get("community_college"):    flags.append("Community College")
    score = len(flags)
    flag_s = "  ✓ " + " · ".join(flags) if flags else ""
    return f"  [{idx}] {name} — {score}/6{flag_s}"


def main():
    try:
        ctx = json.loads(sys.stdin.read() or "{}")
    except Exception:
        sys.exit(0)

    tool_response = ctx.get("tool_response", {})
    if not isinstance(tool_response, dict):
        sys.exit(0)

    # ── Jobs ──────────────────────────────────────────────────────────────────
    jobs = tool_response.get("jobs") or tool_response.get("pending_approvals") or []
    if jobs:
        social   = [j for j in jobs if _is_social(j.get("url", ""))]
        relevant = [j for j in jobs if not _is_social(j.get("url", "")) and _is_relevant_job(j)]
        skipped  = len(jobs) - len(social) - len(relevant)

        lines = [
            f"SYSTEM REMINDER: {len(jobs)} job(s) retrieved — "
            f"{len(relevant)} match our focus areas, {skipped} filtered out, {len(social)} social media (auto-skip).",
            "",
            "Present EACH relevant job one at a time via AskUserQuestion.",
            "Format for each job question:",
            "  question: '<Job Title> at <Company>'",
            "  description: one-line summary of what the role involves",
            "  options:",
            "    • label='Apply'        description='Approve this job and start the assessment'",
            "    • label='See Details'  description='Show full job description and requirements first'",
            "    • label='Open Page'    description='Open the job listing in the browser'",
            "    • label='Skip'         description='Not interested — move to the next one'",
            "",
            "On [Apply]       → call mcp__vps__approve_job(job_id=N)",
            "On [See Details] → call mcp__vps__get_job(job_id=N), display description, re-present the 4 options",
            "On [Open Page]   → call mcp__browser__navigate(url=job['url'])",
            "On [Skip]        → call mcp__vps__skip_job(job_id=N), move to next",
            "",
            f"Relevant jobs to present ({len(relevant)}):",
        ]
        for i, j in enumerate(relevant, 1):
            lines.append(_format_job(j, i))

        if not relevant:
            lines.append("  (none matched our focus areas — nothing to present)")

        print(json.dumps({"type": "system", "content": "\n".join(lines)}))
        sys.exit(0)

    # ── Schools ───────────────────────────────────────────────────────────────
    schools = tool_response.get("schools", [])
    if schools:
        lines = [
            f"SYSTEM REMINDER: {len(schools)} school(s) retrieved.",
            "",
            "Present EACH school one at a time via AskUserQuestion.",
            "Format for each school question:",
            "  question: '<School Name>'",
            "  description: criteria badges (No ID · No Transcript · Monthly Start etc.)",
            "  options:",
            "    • label='Enroll'       description='Open enrollment page and start the process'",
            "    • label='See Details'  description='Show full evidence, criteria, and school info'",
            "    • label='Shortlist'    description='Save this school to review later'",
            "    • label='Skip'         description='Not a fit — move to the next one'",
            "",
            "On [Enroll]      → call mcp__browser__navigate(url=school['enrollment_url'] or school['url'])",
            "On [See Details] → display evidence text + all criteria flags, re-present the 4 options",
            "On [Shortlist]   → note the school name, continue to next",
            "On [Skip]        → move to next school",
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
