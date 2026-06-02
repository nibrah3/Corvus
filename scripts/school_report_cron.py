"""
school_report_cron.py — Scheduled every 6 hours by Windows Task Scheduler.
Sends PDFs of top-scoring schools (score >= 2) to Telegram automatically,
with no user prompt needed — filters are pre-applied.
"""
from __future__ import annotations

import logging
import os
import sys
import time

# Load .env from project root
_root = os.path.dirname(os.path.dirname(__file__))
_env  = os.path.join(_root, ".env")
if os.path.exists(_env):
    for _line in open(_env).read().splitlines():
        if "=" in _line and not _line.startswith("#"):
            _k, _, _v = _line.partition("=")
            if _k.strip() not in os.environ:
                os.environ[_k.strip()] = _v.strip()

sys.path.insert(0, _root)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
    handlers=[
        logging.FileHandler(os.path.join(_root, "logs", "school_cron.log"), encoding="utf-8"),
        logging.StreamHandler(),
    ],
)
log = logging.getLogger("school_cron")

# Default filters — all six criteria; school must pass >= 2 to be included
DEFAULT_FILTERS = [
    "no_transcript_required",
    "monthly_enrollment",
    "community_college",
    "no_id_verification",
    "instant_acceptance",
    "monthly_refund",
]
MIN_SCORE = 2
LIMIT     = 20


def main() -> None:
    try:
        import psycopg2
        import psycopg2.extras
    except ImportError:
        log.error("psycopg2 not installed — aborting")
        sys.exit(1)

    from schools_mcp._pdf    import generate as generate_pdf
    from schools_mcp._notify import send_school_pdf, notify_text

    DSN = os.environ.get(
        "VPS_PG_DSN",
        "postgresql://corvus:corvus-local-password@127.0.0.1:5433/careerbridge",
    )

    log.info("School report cron starting (min_score=%d, limit=%d)", MIN_SCORE, LIMIT)

    try:
        conn = psycopg2.connect(DSN, connect_timeout=10)
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute(
                """
                SELECT name, url, enrollment_url, type, evidence,
                       community_college, no_id_verification, no_transcript_required,
                       monthly_enrollment, instant_acceptance, monthly_refund,
                       filters, criteria_score, city, state
                FROM schools
                WHERE criteria_score >= %s
                  AND filters && %s::text[]
                ORDER BY criteria_score DESC, name
                LIMIT %s
                """,
                (MIN_SCORE, DEFAULT_FILTERS, LIMIT),
            )
            rows = [dict(r) for r in cur.fetchall()]
        conn.close()
    except Exception as e:
        log.error("DB query failed: %s", e)
        sys.exit(1)

    if not rows:
        log.info("No schools matched the filters — nothing to send")
        notify_text("📚 School cron: no schools matched filters (score >= 2). Run discover_schools to populate.")
        return

    notify_text(
        f"📚 *Scheduled school report* — {len(rows)} schools matched "
        f"(score ≥ {MIN_SCORE}, filters: {', '.join(DEFAULT_FILTERS[:3])} + more)"
    )

    sent = failed = 0
    for school in rows:
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
        f"✅ *School cron complete*\n"
        f"Sent: {sent}  Failed: {failed}  Matched: {len(rows)}"
    )
    log.info("Done. sent=%d failed=%d matched=%d", sent, failed, len(rows))


if __name__ == "__main__":
    main()
