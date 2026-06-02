#!/usr/bin/env python3
"""
enrich_jobs.py — Job enrichment pipeline.

For every unenriched job:
  1. Firecrawl the platform URL (LinkedIn, WorkSpark, etc.) to get listing content
  2. Extract the official employer URL — the company's own careers page or ATS listing
  3. Firecrawl the official URL for the authoritative job description
  4. Update the DB: official_url, official_description, enriched=True
  5. If no official URL can be found: mark quality_issue='no_official_url' (still enriched=True
     so we don't retry endlessly — operator sees the warning in the job card)

After enrichment, generate a batch PDF and send to all Telegram users.

Usage:
  python enrich_jobs.py             # run once, block until done
  python enrich_jobs.py --background # run, then generate PDF + broadcast
"""
from __future__ import annotations

import json
import logging
import os
import re
import sys
import time
from pathlib import Path
from urllib.parse import urlparse

import requests

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("enrich_jobs")

# ── Load .env ──────────────────────────────────────────────────────────────────
_ENV = Path(__file__).parent.parent / ".env"
if _ENV.exists():
    for _line in _ENV.read_text(encoding="utf-8").splitlines():
        if "=" in _line and not _line.startswith("#"):
            _k, _, _v = _line.partition("=")
            if _k.strip() not in os.environ:
                os.environ[_k.strip()] = _v.strip()

PG_DSN    = os.environ.get("VPS_PG_DSN", "postgresql://corvus:corvus-local-password@127.0.0.1:5433/careerbridge")
FC_BASE   = os.environ.get("FIRECRAWL_API", "http://localhost:7788/v1")
FC_KEY    = os.environ.get("FIRECRAWL_API_KEY", "")
TG_TOKEN  = os.environ.get("TELEGRAM_BOT_TOKEN", "")
TG_IDS    = []
for _key in ("TELEGRAM_ADMIN_CHAT_ID", "TELEGRAM_ADMIN_CHAT_ID_2"):
    for _part in os.environ.get(_key, "").replace(";", ",").split(","):
        if _part.strip() and _part.strip() not in TG_IDS:
            TG_IDS.append(_part.strip())

# ── Domain classifiers ─────────────────────────────────────────────────────────

# Pure aggregators — NOT official employer URLs
AGGREGATOR_DOMAINS = {
    "linkedin.com", "indeed.com", "glassdoor.com", "workspark.com",
    "ziprecruiter.com", "monster.com", "careerbuilder.com", "simplyhired.com",
    "jobs.google.com", "google.com", "facebook.com", "twitter.com",
    "craigslist.org", "snagajob.com", "jooble.org", "adzuna.com",
}

# ATS platforms that host official job postings on behalf of employers
# These ARE official application URLs (employer controls the listing)
ATS_DOMAINS = {
    "lever.co", "greenhouse.io", "ashbyhq.com", "boards.greenhouse.io",
    "jobs.lever.co", "workday.com", "myworkdayjobs.com", "taleo.net",
    "icims.com", "smartrecruiters.com", "breezy.hr", "recruitee.com",
    "bamboohr.com", "jobvite.com", "successfactors.com", "oracle.com",
    "apply.workable.com", "workable.com", "rippling.com",
}

URL_RE = re.compile(r'https?://[^\s\'"<>()\[\]{}|\\^`]+', re.I)

# ── Job type taxonomy ──────────────────────────────────────────────────────────

JOB_TYPES = {
    "ai_training":        "AI Training & RLHF",
    "data_annotation":    "Data Annotation & Labeling",
    "search_rating":      "Search Quality Rating",
    "transcription":      "Transcription & Captioning",
    "translation":        "Translation & Localization",
    "content_writing":    "Content Writing & Copywriting",
    "social_media":       "Social Media Management",
    "virtual_assistant":  "Virtual Assistant / Admin",
    "customer_support":   "Customer Support / BPO",
    "microtask":          "Microtasks",
    "tutoring":           "Online Tutoring & Teaching",
    "testing":            "Software / App Testing",
    "moderation":         "Content Moderation",
    "gpt":                "Get Paid To (GPT)",
    "other_gig":          "Other Gig / Remote Task",
}

# ── Claude gate prompt ─────────────────────────────────────────────────────────

_GATE_SYSTEM = """\
You are a gig-work quality filter for a platform that helps people earn income from \
accessible remote tasks — no degree, no professional license required.

BLOCK (keep=false) if the role is:
- Software / systems engineering (SWE, DevOps, SRE, Data Engineer, ML Engineer, Platform Eng)
- Licensed professions: medicine, nursing, pharmacy, law, CPA accounting, architecture, \
financial advising, civil/mechanical/electrical engineering
- Full-time corporate management, director, VP, or C-suite roles
- Academic research faculty or tenured professor
- Skilled trades requiring apprenticeship (electrician, plumber, HVAC tech)
- A blog post, news article, press release, or SEO page — NOT an actual job posting
- Posting so vague that no real requirements can be extracted

KEEP (keep=true) for any of these:
- AI/ML training tasks: prompt writing, RLHF, red-teaming, evaluation, feedback rating
- Data annotation/labeling: images, video, text, audio, bounding boxes, NLP tagging
- Search quality rating, web evaluation, EEAT scoring, internet assessor
- Transcription, captioning, subtitling (any audio/video to text)
- Translation, localization, post-editing machine translation
- Content writing, copywriting, blogging, editing, proofreading
- Social media management, scheduling, community management
- Virtual assistant, data entry, scheduling, admin support
- Customer support, chat support, email support, BPO
- Microtasks: click tasks, survey completion, verification tasks
- GPT / Get-Paid-To: paid surveys, cashback offers, watching videos, app installs
- Online tutoring, teaching, academic coaching, language instruction
- Software / app / website usability testing, QA tester, bug bounty
- Content moderation, trust & safety review

job_type values — pick EXACTLY ONE from this list:
  ai_training, data_annotation, search_rating, transcription, translation,
  content_writing, social_media, virtual_assistant, customer_support,
  microtask, tutoring, testing, moderation, gpt, other_gig

Return ONLY valid JSON with no markdown fences:
{
  "keep": true or false,
  "block_reason": null or one of "professional_job|blog_post|no_requirements|vague",
  "job_type": "<type from list, null if keep=false>",
  "requirements": "<2-3 sentence plain-English summary of actual requirements, null if keep=false>",
  "official_url": "<best direct application or registration URL found in the content, or empty string>"
}\
"""


def _domain(url: str) -> str:
    try:
        host = urlparse(url).netloc.lower()
        return host.lstrip("www.")
    except Exception:
        return ""


def _is_aggregator(url: str) -> bool:
    d = _domain(url)
    return any(d == agg or d.endswith("." + agg) for agg in AGGREGATOR_DOMAINS)


def _is_ats(url: str) -> bool:
    d = _domain(url)
    return any(d == ats or d.endswith("." + ats) for ats in ATS_DOMAINS)


# ── Firecrawl ──────────────────────────────────────────────────────────────────

def _firecrawl(url: str, timeout: int = 25) -> str | None:
    """Scrape a URL via self-hosted Firecrawl, return markdown text or None."""
    try:
        headers = {"Content-Type": "application/json"}
        if FC_KEY:
            headers["Authorization"] = f"Bearer {FC_KEY}"
        r = requests.post(
            f"{FC_BASE}/scrape",
            headers=headers,
            json={
                "url": url,
                "formats": ["markdown"],
                "onlyMainContent": True,
                "waitFor": 2000,
                "timeout": timeout * 1000,
            },
            timeout=timeout + 5,
        )
        if not r.ok:
            log.debug("Firecrawl %s → %d", url, r.status_code)
            return None
        data = r.json().get("data", {})
        md = data.get("markdown") or data.get("content") or ""
        return md if len(md) > 80 else None
    except Exception as e:
        log.debug("Firecrawl error for %s: %s", url, e)
        return None


def _requests_get(url: str) -> str | None:
    """Lightweight fallback scrape via requests."""
    try:
        r = requests.get(url, timeout=12, allow_redirects=True,
                         headers={"User-Agent": "Mozilla/5.0"})
        if not r.ok:
            return None
        text = r.text[:15000]
        # Strip tags crudely
        text = re.sub(r"<[^>]+>", " ", text)
        text = re.sub(r"\s+", " ", text).strip()
        return text if len(text) > 80 else None
    except Exception:
        return None


# ── Official URL extraction ────────────────────────────────────────────────────

def _extract_official_url(platform_url: str, content: str) -> str | None:
    """
    Given the scraped content of a platform job listing, find the official employer URL.

    Priority:
    1. If the platform URL itself is an ATS URL → it IS official
    2. Find URLs in content that are on ATS domains → official
    3. Find non-aggregator, non-platform URLs with job-related keywords → official
    4. Find any non-aggregator URL with a company-like domain → best guess
    """
    # 1. Platform URL is already an ATS listing
    if _is_ats(platform_url):
        return platform_url

    all_urls = URL_RE.findall(content)

    # 2. ATS URLs in content
    for u in all_urls:
        if _is_ats(u) and not _is_aggregator(u):
            return u.rstrip(".,;)")

    # 3. Non-aggregator URLs with job-related path segments
    job_path_re = re.compile(r"/(?:jobs?|careers?|apply|opening|position|role|vacancy|work-with-us)", re.I)
    for u in all_urls:
        if not _is_aggregator(u) and job_path_re.search(u):
            return u.rstrip(".,;)")

    # 4. Any non-aggregator, non-social URL
    social = {"twitter.com", "x.com", "facebook.com", "instagram.com",
              "youtube.com", "reddit.com", "tiktok.com", "t.co"}
    for u in all_urls:
        d = _domain(u)
        if not _is_aggregator(u) and not any(d == s or d.endswith("." + s) for s in social):
            return u.rstrip(".,;)")

    return None


# ── Claude gate ────────────────────────────────────────────────────────────────

_OR_KEY   = os.environ.get("OPENROUTER_API_KEY", "")
_OR_BASE  = "https://openrouter.ai/api/v1"
_OR_MODEL = "anthropic/claude-sonnet-4-6"


def _claude_gate(job: dict, content: str) -> dict | None:
    """
    Pass a job through the Claude quality gate.

    Returns a cleaned dict with job_type, requirements, official_url
    if the job passes, or None if it should be blocked.

    The gate blocks professional/licensed roles, blog posts, and vague listings.
    """
    if not _OR_KEY:
        log.warning("OPENROUTER_API_KEY not set — gate disabled, passing all jobs")
        return {"job_type": "other_gig", "requirements": "", "official_url": ""}

    title   = (job.get("title") or "").strip()
    company = (job.get("company") or "").strip()
    snippet = content[:5000] if content else ""

    user_msg = (
        f"Title: {title}\n"
        f"Company: {company}\n"
        f"Discovery URL: {job.get('url', '')}\n\n"
        f"Page content:\n{snippet}"
    )

    try:
        from openai import OpenAI
        client = OpenAI(api_key=_OR_KEY, base_url=_OR_BASE)
        resp = client.chat.completions.create(
            model=_OR_MODEL,
            max_tokens=400,
            temperature=0,
            messages=[
                {"role": "system", "content": _GATE_SYSTEM},
                {"role": "user",   "content": user_msg},
            ],
        )
        raw = (resp.choices[0].message.content or "").strip()
        if raw.startswith("```"):
            raw = raw.split("\n", 1)[1].rsplit("```", 1)[0].strip()
        import json as _json
        result = _json.loads(raw)
    except Exception as e:
        log.warning("Gate LLM call failed for '%s': %s — passing through", title[:40], e)
        return {"job_type": "other_gig", "requirements": "", "official_url": ""}

    if not result.get("keep"):
        reason = result.get("block_reason") or "unknown"
        log.info("Gate BLOCKED '%s': %s", title[:40], reason)
        return None

    return {
        "job_type":    result.get("job_type") or "other_gig",
        "requirements": result.get("requirements") or "",
        "official_url": result.get("official_url") or "",
    }


# ── DB helpers ─────────────────────────────────────────────────────────────────

def _pg():
    import psycopg2
    return psycopg2.connect(PG_DSN, connect_timeout=8)


def _ensure_columns(conn) -> None:
    with conn.cursor() as cur:
        cur.execute("""
            ALTER TABLE jobs
                ADD COLUMN IF NOT EXISTS official_url         TEXT,
                ADD COLUMN IF NOT EXISTS official_description TEXT,
                ADD COLUMN IF NOT EXISTS enriched             BOOLEAN DEFAULT FALSE,
                ADD COLUMN IF NOT EXISTS quality_issue        TEXT,
                ADD COLUMN IF NOT EXISTS source_url           TEXT,
                ADD COLUMN IF NOT EXISTS job_type             TEXT
        """)
    conn.commit()


def _get_unenriched(conn, limit: int = 100) -> list[dict]:
    import psycopg2.extras
    with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
        cur.execute(
            """
            SELECT id, url, title, company, source
            FROM jobs
            WHERE (enriched IS FALSE OR enriched IS NULL)
              AND status NOT IN ('skipped', 'completed', 'blocked')
            ORDER BY discovered_at DESC
            LIMIT %s
            """,
            (limit,),
        )
        return [dict(r) for r in cur.fetchall()]


def _update_enrichment(conn, job_id: int, official_url: str | None,
                        official_description: str | None, quality_issue: str | None,
                        source_url: str | None = None,
                        job_type: str | None = None) -> None:
    with conn.cursor() as cur:
        cur.execute(
            """
            UPDATE jobs
            SET official_url         = %s,
                official_description = %s,
                enriched             = TRUE,
                quality_issue        = %s,
                source_url           = COALESCE(%s, source_url),
                job_type             = COALESCE(%s, job_type)
            WHERE id = %s
            """,
            (official_url, official_description, quality_issue,
             source_url, job_type, job_id),
        )
    conn.commit()


def _block_job(conn, job_id: int, block_reason: str) -> None:
    """Mark a job as blocked by the quality gate."""
    with conn.cursor() as cur:
        cur.execute(
            """
            UPDATE jobs
            SET status       = 'blocked',
                enriched     = TRUE,
                quality_issue = %s
            WHERE id = %s
            """,
            (block_reason, job_id),
        )
    conn.commit()


# ── Bulk-block obvious non-jobs (no LLM needed) ───────────────────────────────
# Runs at the start of every enrichment cycle before the LLM gate.
# These patterns are 100% certain non-gig-work — blocking via SQL is
# cheaper and faster than spending an API call on each one.

_BULK_RULES = [
    ("source = 'us_schools'",                                          "school_page_in_jobs_table"),
    ("url LIKE '%%news.ycombinator.com%%'",                            "hn_comment_not_job"),
    ("url LIKE '%%reddit.com%%' AND source = 'reddit'",               "reddit_post_not_job"),
    ("url LIKE '%%indeed.com%%' AND (title ILIKE 'apply at%%' OR title ILIKE 'open enrollment%%')",
                                                                       "school_enrollment_page"),
    ("url LIKE '%%ycombinator.com/jobs%%'",                            "hn_jobs_page_not_listing"),
]


def _bulk_block_obvious(conn) -> int:
    """
    SQL-based instant blocking for jobs that are obviously not gig work.
    Returns count of newly-blocked jobs.
    """
    total = 0
    with conn.cursor() as cur:
        for where_clause, reason in _BULK_RULES:
            cur.execute(
                f"""
                UPDATE jobs
                SET status = 'blocked', enriched = TRUE, quality_issue = %s
                WHERE ({where_clause})
                  AND status NOT IN ('blocked', 'completed', 'applied', 'skipped')
                """,
                (reason,),
            )
            total += cur.rowcount
    conn.commit()
    if total:
        log.info("Bulk-blocked %d obvious non-jobs (school pages, HN threads, etc.)", total)
    return total


# ── Per-job enrichment ────────────────────────────────────────────────────────

def enrich_job(job: dict) -> dict:
    """
    Enrich a single job dict.

    Pipeline:
      1. Firecrawl the discovery URL
      2. Claude gate — classifies job_type, blocks professional/non-job content
      3. Resolve and scrape the official company career URL
      4. Return enriched dict (or dict with block_reason set)
    """
    job_id      = job["id"]
    platform_url = job["url"]
    title       = job.get("title") or "Job"
    company     = job.get("company") or "Unknown"

    log.info("[%d] Enriching: %s @ %s", job_id, title[:40], company[:30])

    # Step 1: Scrape discovery/platform listing
    content = _firecrawl(platform_url) or _requests_get(platform_url) or ""

    if not content:
        log.warning("[%d] Could not scrape platform URL: %s", job_id, platform_url)
        return {**job, "official_url": None, "official_description": None,
                "quality_issue": "platform_scrape_failed",
                "source_url": platform_url, "job_type": None}

    # Step 2: Claude quality gate
    gated = _claude_gate(job, content)
    if gated is None:
        # Blocked — caller will call _block_job()
        return {**job, "official_url": None, "official_description": None,
                "quality_issue": "blocked_by_gate",
                "source_url": platform_url, "job_type": None, "_blocked": True}

    job_type = gated["job_type"]
    requirements = gated["requirements"]
    # Gate may have found a better official URL than the heuristic extractor
    gate_official_url = gated["official_url"]

    # Step 3: Resolve official URL — prefer gate result, fall back to heuristics
    official_url = (gate_official_url
                    or _extract_official_url(platform_url, content)
                    or None)

    if not official_url:
        log.warning("[%d] No official URL found for: %s", job_id, platform_url)
        return {**job, "official_url": None,
                "official_description": requirements or None,
                "quality_issue": "no_official_url",
                "source_url": platform_url, "job_type": job_type}

    log.info("[%d] [%s] Official URL: %s", job_id, job_type, official_url[:80])

    # Step 4: Scrape official URL for authoritative requirements
    if official_url == platform_url:
        official_description = requirements or content[:3000]
    else:
        official_content = _firecrawl(official_url) or _requests_get(official_url) or ""
        # Prefer Claude-extracted requirements if we have them; use full scrape as fallback
        official_description = requirements or (official_content[:4000] if official_content else "")

    return {
        **job,
        "official_url":         official_url,
        "official_description": official_description or None,
        "quality_issue":        None,
        "source_url":           platform_url,
        "job_type":             job_type,
    }


# ── Telegram broadcast ────────────────────────────────────────────────────────

def _tg_send_doc(pdf_bytes: bytes, filename: str, caption: str) -> int:
    if not TG_TOKEN or not TG_IDS:
        return 0
    sent = 0
    for chat_id in TG_IDS:
        try:
            r = requests.post(
                f"https://api.telegram.org/bot{TG_TOKEN}/sendDocument",
                data={"chat_id": chat_id, "caption": caption, "parse_mode": "Markdown"},
                files={"document": (filename, pdf_bytes, "application/pdf")},
                timeout=60,
            )
            if r.ok:
                sent += 1
        except Exception as e:
            log.warning("Telegram send error (chat %s): %s", chat_id, e)
    return sent


def _tg_notify(text: str) -> None:
    if not TG_TOKEN or not TG_IDS:
        return
    for chat_id in TG_IDS:
        try:
            requests.post(
                f"https://api.telegram.org/bot{TG_TOKEN}/sendMessage",
                json={"chat_id": chat_id, "text": text, "parse_mode": "Markdown"},
                timeout=10,
            )
        except Exception:
            pass


# ── Main ──────────────────────────────────────────────────────────────────────

def run(limit: int = 100) -> list[dict]:
    """Run enrichment. Returns list of enriched job dicts."""
    try:
        conn = _pg()
    except Exception as e:
        log.error("DB connection failed: %s", e)
        return []

    try:
        _ensure_columns(conn)

        # ── Step 0: Bulk-block obvious non-jobs before hitting the LLM gate ──
        # Instantly removes school enrollment pages, HN threads, Reddit posts
        # and other known-bad URL patterns. No API calls needed for these.
        _bulk_block_obvious(conn)

        jobs = _get_unenriched(conn, limit)
        if not jobs:
            log.info("No unenriched jobs found.")
            return []

        log.info("Enriching %d job(s)...", len(jobs))
        enriched: list[dict] = []

        for job in jobs:
            try:
                result = enrich_job(job)
                if result.get("_blocked"):
                    _block_job(conn, result["id"], result.get("quality_issue", "blocked_by_gate"))
                    log.info("[%d] Blocked: %s", result["id"], result.get("quality_issue"))
                else:
                    _update_enrichment(
                        conn,
                        result["id"],
                        result.get("official_url"),
                        result.get("official_description"),
                        result.get("quality_issue"),
                        source_url=result.get("source_url"),
                        job_type=result.get("job_type"),
                    )
                    enriched.append(result)
            except Exception as e:
                log.warning("[%s] Enrichment error: %s", job.get("id"), e)
            time.sleep(0.5)

        ok      = sum(1 for j in enriched if j.get("official_url"))
        bad     = sum(1 for j in enriched if not j.get("official_url"))
        log.info("Done. %d enriched OK, %d quality issues", ok, bad)
        return enriched

    finally:
        conn.close()


def broadcast_jobs_pdf(enriched_jobs: list[dict]) -> None:
    """Generate a batch PDF of all enriched jobs and broadcast to all Telegram users."""
    if not enriched_jobs:
        return
    try:
        # Import jobs_pdf from same scripts directory
        sys.path.insert(0, str(Path(__file__).parent))
        from jobs_pdf import generate_batch
        pdf_bytes = generate_batch(enriched_jobs)
        ts = time.strftime("%Y%m%d_%H%M")
        fname = f"jobs_discovery_{ts}.pdf"
        ok_count  = sum(1 for j in enriched_jobs if j.get("official_url"))
        bad_count = sum(1 for j in enriched_jobs if not j.get("official_url"))
        caption = (
            f"*Job Discovery Report*\n"
            f"{len(enriched_jobs)} job(s) found — {ts}\n"
            f"Official URL confirmed: {ok_count} | Quality warnings: {bad_count}\n"
            f"Use the Jobs menu to review and apply."
        )
        sent = _tg_send_doc(pdf_bytes, fname, caption)
        log.info("Broadcast jobs PDF to %d chat(s)", sent)
    except Exception as e:
        log.warning("Jobs PDF broadcast failed: %s", e)


if __name__ == "__main__":
    enriched = run(limit=100)
    if enriched:
        broadcast_jobs_pdf(enriched)
    result = {
        "enriched": len(enriched),
        "ok":  sum(1 for j in enriched if j.get("official_url")),
        "quality_issues": sum(1 for j in enriched if not j.get("official_url")),
    }
    print(json.dumps(result))
