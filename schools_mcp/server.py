"""
schools_mcp — School discovery MCP server.
Port: 8714

Tools:
  discover_schools(limit, state)        — start a background discovery job (stores ALL schools)
  get_discovery_status(job_id)          — poll job progress
  send_school_reports(filters, custom_query, min_score, limit)
                                        — generate + send PDFs to Telegram for filtered results
  list_confirmed_schools(filters, min_score, limit)
                                        — query DB (no Telegram send)
"""
from __future__ import annotations

import logging
import os
import sys
import threading
import time
import uuid

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

for _line in open(os.path.join(os.path.dirname(__file__), "..", ".env")).read().splitlines():
    if "=" in _line and not _line.startswith("#"):
        _k, _, _v = _line.partition("=")
        if _k.strip() not in os.environ:
            os.environ[_k.strip()] = _v.strip()

from _minmcp import MinMCP
from schools_mcp._gov_api   import fetch_candidates
from schools_mcp._crawler   import crawl_school
from schools_mcp._analyzer  import analyze, CRITERIA, CRITERIA_LABELS
from schools_mcp._pdf       import generate as generate_pdf
from schools_mcp._notify    import send_school_pdf, notify_text
from schools_mcp._db        import ensure_table, save, was_recently_processed, url_hash

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("schools_mcp")

mcp = MinMCP("schools")

_jobs: dict[str, dict] = {}
_jobs_lock = threading.Lock()


# ── Discovery pipeline ────────────────────────────────────────────────────────

def _run_pipeline(job_id: str, limit: int, state: str, filters: list) -> None:
    def _update(**kw):
        with _jobs_lock:
            _jobs[job_id].update(kw)

    try:
        notify_text(
            f"🔍 *School discovery started* (job `{job_id}`)\n"
            f"Limit: {limit}{f'  State: {state}' if state else ''}\n"
            f"All discovered schools will be stored. "
            f"Use the filter tool to browse results in Telegram."
        )

        ensure_table()

        # ── Round 1: Government API ───────────────────────────────────────────
        log.info("[%s] Round 1: College Scorecard API (limit=%d)", job_id, limit)
        _update(phase="gov_api")
        candidates = fetch_candidates(filters=filters or [], limit=limit)
        _update(candidates=len(candidates))

        if not candidates:
            _update(status="done", error="No candidates from gov API — check SCORECARD_API_KEY")
            notify_text(f"⚠️ Job `{job_id}`: No candidates from College Scorecard. Check SCORECARD_API_KEY.")
            return

        log.info("[%s] %d candidates from gov API", job_id, len(candidates))

        session_seen: set[str] = set()
        stored = skipped_db = skipped_session = errors = 0
        stored_schools: list[dict] = []

        # ── Round 2: Crawl + Analyze (no filter gate — store everything) ─────
        _update(phase="crawling", total=len(candidates))

        for i, school in enumerate(candidates):
            _update(processed=i + 1)
            name  = school["name"]
            uhash = url_hash(school["url"])

            # Session dedup
            if uhash in session_seen:
                skipped_session += 1
                continue
            session_seen.add(uhash)

            # DB dedup — skip if processed within 7 days
            if was_recently_processed(school["url"]):
                skipped_db += 1
                log.debug("[%s] db dedup: %s", job_id, name[:40])
                continue

            # State filter
            if state and school.get("state", "").upper() != state.upper():
                continue

            log.info("[%s] [%d/%d] %s", job_id, i + 1, len(candidates), name[:50])

            try:
                crawled  = crawl_school(school)
                analyzed = analyze(crawled)
            except Exception as e:
                log.warning("[%s] Failed %s: %s", job_id, name[:40], e)
                errors += 1
                continue

            # Attach discovery source URL (College Scorecard API record for this school)
            scorecard_id = school.get("scorecard_id")
            analyzed["source_url"] = (
                f"https://api.data.ed.gov/student/v1/schools/{scorecard_id}"
                if scorecard_id else "college_scorecard_api"
            )

            # Save to DB regardless of score — filtering happens via hook
            if save(analyzed):
                stored += 1
                stored_schools.append(analyzed)
                _update(stored=stored)
                log.info(
                    "[%s] Saved: %s — score %d/6 — %s",
                    job_id, name[:40],
                    analyzed.get("criteria_score", 0),
                    analyzed.get("filters") or ["none"],
                )

            time.sleep(0.5)

        summary = (
            f"✅ *School discovery complete* (job `{job_id}`)\n"
            f"Candidates: {len(candidates)}  "
            f"Stored: {stored}  "
            f"Skipped (recent): {skipped_db}  "
            f"Skipped (dup): {skipped_session}  "
            f"Errors: {errors}\n\n"
            f"Use the schools filter in Claude Code to browse results."
        )
        notify_text(summary)
        _update(
            status="done",
            stored=stored,
            skipped_db=skipped_db,
            skipped_session=skipped_session,
            errors=errors,
        )
        log.info("[%s] Done. stored=%d", job_id, stored)

        # Broadcast batch PDF to all users if anything was stored this run
        if stored_schools:
            try:
                import tempfile, os as _os
                from schools_mcp._pdf import generate_batch
                from schools_mcp._notify import broadcast_pdf
                pdf_bytes = generate_batch(stored_schools[:100])
                ts_str = time.strftime("%Y%m%d_%H%M")
                fname = f"schools_discovery_{ts_str}.pdf"
                with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as tmp:
                    tmp.write(pdf_bytes)
                    tmp_path = tmp.name
                caption = (
                    f"*School Discovery Report*\n"
                    f"{stored} new school(s) found — {ts_str}\n"
                    f"Use the Schools menu to browse and send individual reports."
                )
                sent = broadcast_pdf(pdf_bytes, fname, caption)
                log.info("[%s] Batch PDF broadcast to %d chat(s)", job_id, sent)
                try:
                    _os.unlink(tmp_path)
                except Exception:
                    pass
            except Exception as e:
                log.warning("[%s] Batch PDF failed: %s", job_id, e)

    except Exception as e:
        log.exception("[%s] Pipeline error: %s", job_id, e)
        _update(status="error", error=str(e))
        notify_text(f"❌ School discovery `{job_id}` crashed: {str(e)[:200]}")


# ── MCP Tools ─────────────────────────────────────────────────────────────────

@mcp.tool()
def discover_schools(limit: int = 500, state: str = "", filters: list = None) -> dict:
    """
    Discover US schools via the College Scorecard API then crawl each with
    Firecrawl + Claude Sonnet analysis. ALL discovered schools are stored
    to the database regardless of criteria score.

    Args:
        limit:   Max candidates to pull from the gov API (default 500, max 500).
        state:   Optional two-letter US state code to restrict search (e.g. 'CA').
        filters: Criteria to pre-filter candidates from the gov API. Any of:
                 community_college, no_id_verification, no_transcript_required,
                 monthly_enrollment, instant_acceptance, monthly_refund.
                 Empty list = fetch all school types (broadest search).
    """
    limit = max(1, min(limit, 500))
    filters = filters or []

    job_id = uuid.uuid4().hex[:8]
    with _jobs_lock:
        _jobs[job_id] = {
            "status":    "running",
            "phase":     "starting",
            "candidates": 0,
            "processed":  0,
            "stored":     0,
            "limit":     limit,
            "state":     state,
            "filters":   filters,
        }

    threading.Thread(
        target=_run_pipeline,
        args=(job_id, limit, state, filters),
        daemon=True,
    ).start()

    return {
        "job_id":  job_id,
        "status":  "started",
        "message": (
            f"Discovery job {job_id} started — up to {limit} candidates"
            f"{f' in {state}' if state else ''}. "
            "All schools will be stored. "
            "Results arrive via Telegram summary when complete. "
            "To browse schools, call send_school_reports with your filter preferences."
        ),
    }


@mcp.tool()
def get_discovery_status(job_id: str) -> dict:
    """
    Check the status of a running or completed school discovery job.

    Args:
        job_id: The job_id returned by discover_schools.
    """
    with _jobs_lock:
        job = _jobs.get(job_id)
    if not job:
        return {"error": f"Job '{job_id}' not found (may be from a previous server session)."}
    return dict(job)


@mcp.tool()
def send_school_reports(
    filters: list = None,
    custom_query: str = "",
    min_score: int = 1,
    limit: int = 20,
) -> dict:
    """
    Query confirmed schools from the database, generate a PDF for each match,
    and send all PDFs to Telegram. Triggered by the schools_filter hook after
    the user selects their preferred criteria via AskUserQuestion.

    Args:
        filters:      List of criteria keys to filter on. Any of:
                      community_college, no_id_verification, no_transcript_required,
                      monthly_enrollment, instant_acceptance, monthly_refund.
                      Empty = return all schools with min_score or above.
        custom_query: Free-text description of additional requirements.
                      Sent as a Telegram message before the PDF batch.
        min_score:    Minimum criteria score (0-6). Default 1.
        limit:        Max schools to send. Default 20.
    """
    try:
        import psycopg2
        import psycopg2.extras
        from schools_mcp._db import _DSN

        # Build SQL — if specific filters requested, school must pass at least one
        if filters:
            sql = """
                SELECT name, url, enrollment_url, type, evidence,
                       community_college, no_id_verification, no_transcript_required,
                       monthly_enrollment, instant_acceptance, monthly_refund,
                       filters, criteria_score, city, state
                FROM schools
                WHERE criteria_score >= %s
                  AND filters && %s::text[]
                ORDER BY criteria_score DESC, name
                LIMIT %s
            """
            params = (min_score, filters, limit)
        else:
            sql = """
                SELECT name, url, enrollment_url, type, evidence,
                       community_college, no_id_verification, no_transcript_required,
                       monthly_enrollment, instant_acceptance, monthly_refund,
                       filters, criteria_score, city, state
                FROM schools
                WHERE criteria_score >= %s
                ORDER BY criteria_score DESC, name
                LIMIT %s
            """
            params = (min_score, limit)

        with psycopg2.connect(_DSN, connect_timeout=10) as c:
            with c.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
                cur.execute(sql, params)
                rows = [dict(r) for r in cur.fetchall()]

    except Exception as e:
        return {"error": f"DB query failed: {e}", "sent": 0}

    if not rows:
        notify_text(
            f"🔍 School filter: no schools found matching "
            f"filters={filters or 'any'}, min_score={min_score}.\n"
            f"Run discover_schools to populate the database."
        )
        return {"sent": 0, "message": "No matching schools in DB."}

    # Custom query notification
    if custom_query:
        notify_text(f"📋 *School search request:*\n_{custom_query}_")

    sent = failed = 0
    for school in rows:
        # evidence column is JSONB — psycopg2 returns it as dict already
        if not isinstance(school.get("evidence"), dict):
            school["evidence"] = {}
        try:
            pdf_bytes = generate_pdf(school)
            if send_school_pdf(school, pdf_bytes):
                sent += 1
            else:
                failed += 1
        except Exception as e:
            log.warning("PDF/send failed for %s: %s", school.get("name", "?")[:40], e)
            failed += 1
        time.sleep(0.3)

    notify_text(
        f"📚 *School report batch complete*\n"
        f"Filters: {', '.join(filters) if filters else 'all'}\n"
        f"Sent: {sent}  Failed: {failed}  Total matched: {len(rows)}"
    )
    return {
        "sent":    sent,
        "failed":  failed,
        "matched": len(rows),
        "filters": filters or [],
    }


@mcp.tool()
def list_confirmed_schools(
    filters: list = None,
    min_score: int = 1,
    limit: int = 50,
) -> dict:
    """
    List confirmed schools from the database without sending to Telegram.
    Use send_school_reports to get PDF reports in Telegram.

    Args:
        filters:   Criteria keys to filter on (same set as send_school_reports).
        min_score: Minimum criteria score. Default 1.
        limit:     Max results. Default 50.
    """
    try:
        import psycopg2
        import psycopg2.extras
        from schools_mcp._db import _DSN

        if filters:
            sql = """
                SELECT name, url, enrollment_url, type, filters, criteria_score,
                       city, state, created_at
                FROM schools
                WHERE criteria_score >= %s AND filters && %s::text[]
                ORDER BY criteria_score DESC, name
                LIMIT %s
            """
            params = (min_score, filters, limit)
        else:
            sql = """
                SELECT name, url, enrollment_url, type, filters, criteria_score,
                       city, state, created_at
                FROM schools
                WHERE criteria_score >= %s
                ORDER BY criteria_score DESC, name
                LIMIT %s
            """
            params = (min_score, limit)

        with psycopg2.connect(_DSN, connect_timeout=10) as c:
            with c.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
                cur.execute(sql, params)
                rows = [dict(r) for r in cur.fetchall()]

        return {"count": len(rows), "schools": rows}
    except Exception as e:
        return {"error": str(e), "schools": []}


if __name__ == "__main__":
    mcp.run()
