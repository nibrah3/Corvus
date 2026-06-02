#!/usr/bin/env python3
"""
regate_existing.py — One-shot migration: pass all existing jobs through the Claude gate.

What this does:
  1. Backfills source_url = url for every job that has no source_url yet
  2. Runs every non-blocked, non-completed job through _claude_gate()
  3. Blocked (professional jobs, blog posts): status → 'blocked', quality_issue set
  4. Kept: job_type populated, requirements stored in official_description if missing
  5. Prints a summary table of job_type distribution

Run once from D:\\cb-core:
  python scripts/regate_existing.py
  python scripts/regate_existing.py --dry-run   # preview without writing
  python scripts/regate_existing.py --limit 50  # process first N jobs
"""
from __future__ import annotations

import argparse
import json
import logging
import os
import sys
import time
from pathlib import Path

CB_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(CB_DIR))
sys.path.insert(0, str(CB_DIR / "scripts"))

for _line in (CB_DIR / ".env").read_text(encoding="utf-8").splitlines():
    if "=" in _line and not _line.startswith("#"):
        _k, _, _v = _line.partition("=")
        if _k.strip() not in os.environ:
            os.environ[_k.strip()] = _v.strip()

from enrich_jobs import _claude_gate, _firecrawl, _requests_get, JOB_TYPES

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("regate")

PG_DSN = os.environ.get("VPS_PG_DSN",
         "postgresql://corvus:corvus-local-password@127.0.0.1:5433/careerbridge")


def _pg():
    import psycopg2
    return psycopg2.connect(PG_DSN, connect_timeout=10)


def _ensure_columns(conn) -> None:
    with conn.cursor() as cur:
        cur.execute("""
            ALTER TABLE jobs
                ADD COLUMN IF NOT EXISTS source_url  TEXT,
                ADD COLUMN IF NOT EXISTS job_type    TEXT
        """)
    conn.commit()


def _backfill_source_url(conn) -> int:
    """Copy url → source_url for every row that has no source_url yet."""
    with conn.cursor() as cur:
        cur.execute("""
            UPDATE jobs
            SET source_url = url
            WHERE source_url IS NULL
        """)
        count = cur.rowcount
    conn.commit()
    return count


def _get_jobs_to_regate(conn, limit: int,
                        sources: list[str] | None = None,
                        reclassify_fallback: bool = False) -> list[dict]:
    import psycopg2.extras
    params: list = []
    extra_clauses = []

    if sources:
        placeholders = ",".join(["%s"] * len(sources))
        extra_clauses.append(f"source IN ({placeholders})")
        params.extend(sources)

    if reclassify_fallback:
        # Re-process jobs that got other_gig as a fallback label (LLM call failed)
        # These have job_type='other_gig' but quality_issue IS NULL (not manually set)
        extra_clauses.append("job_type = 'other_gig'")
        extra_clauses.append("quality_issue IS NULL")
        where_type = "OR job_type = 'other_gig'"
    else:
        where_type = ""

    source_clause = ("AND " + " AND ".join(extra_clauses)) if extra_clauses else ""
    params.append(limit)

    with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
        cur.execute(f"""
            SELECT id, url, title, company, source,
                   official_url,
                   description AS official_description
            FROM jobs
            WHERE status NOT IN ('blocked', 'completed', 'skipped')
              AND (job_type IS NULL {where_type})
              {source_clause}
            ORDER BY discovered_at DESC
            LIMIT %s
        """, params)
        return [dict(r) for r in cur.fetchall()]


def _apply_gate_result(conn, job_id: int, result: dict | None,
                        block_reason: str | None, dry_run: bool) -> str:
    if dry_run:
        if result is None:
            return f"BLOCK({block_reason})"
        return f"KEEP({result['job_type']})"

    with conn.cursor() as cur:
        if result is None:
            cur.execute("""
                UPDATE jobs
                SET status='blocked', enriched=TRUE, quality_issue=%s
                WHERE id=%s
            """, (block_reason or "blocked_by_gate", job_id))
        else:
            cur.execute("""
                UPDATE jobs
                SET job_type=%s,
                    description=COALESCE(NULLIF(%s,''), description)
                WHERE id=%s
            """, (result["job_type"],
                  result.get("requirements") or "",
                  job_id))
    conn.commit()
    return f"KEEP({result['job_type']})" if result else f"BLOCK({block_reason})"


def main():
    parser = argparse.ArgumentParser(description="Re-gate existing jobs through Claude")
    parser.add_argument("--dry-run", action="store_true",
                        help="Classify without writing to DB")
    parser.add_argument("--limit", type=int, default=500,
                        help="Max jobs to process (default 500)")
    parser.add_argument("--sources", type=str, default="",
                        help="Comma-separated source values to process (e.g. 'greenhouse,hn_hiring'). "
                             "Empty = all sources.")
    parser.add_argument("--reclassify-fallback", action="store_true",
                        help="Re-classify jobs that got the 'other_gig' fallback due to failed LLM calls. "
                             "Requires job_type='other_gig' AND quality_issue IS NULL (not manually set).")
    args = parser.parse_args()

    conn = _pg()
    _ensure_columns(conn)

    backfilled = _backfill_source_url(conn)
    log.info("Backfilled source_url for %d rows", backfilled)

    source_filter = [s.strip() for s in args.sources.split(",") if s.strip()]
    jobs = _get_jobs_to_regate(conn, args.limit, source_filter,
                               reclassify_fallback=args.reclassify_fallback)
    log.info("Found %d jobs to re-gate%s", len(jobs),
             " (DRY RUN)" if args.dry_run else "")

    if not jobs:
        log.info("Nothing to do.")
        return

    counters: dict[str, int] = {}
    blocked = kept = errors = 0

    for i, job in enumerate(jobs, 1):
        jid   = job["id"]
        title = (job.get("title") or "")[:50]
        url   = job.get("url") or ""

        log.info("[%d/%d] id=%d %s", i, len(jobs), jid, title)

        # Prefer already-scraped official URL content; fall back to platform URL
        scrape_url = job.get("official_url") or url
        content = ""
        if scrape_url:
            content = _firecrawl(scrape_url) or _requests_get(scrape_url) or ""

        try:
            gated = _claude_gate(job, content)
        except Exception as e:
            log.warning("Gate error for id=%d: %s", jid, e)
            errors += 1
            continue

        block_reason = None if gated else "blocked_by_gate"
        outcome = _apply_gate_result(conn, jid, gated, block_reason, args.dry_run)

        if gated is None:
            blocked += 1
        else:
            kept += 1
            counters[gated["job_type"]] = counters.get(gated["job_type"], 0) + 1

        log.info("  → %s", outcome)
        time.sleep(0.3)

    print()
    print("=" * 55)
    print(f"Re-gate complete{'  [DRY RUN — no writes]' if args.dry_run else ''}")
    print(f"  Total processed : {len(jobs)}")
    print(f"  Kept            : {kept}")
    print(f"  Blocked         : {blocked}")
    print(f"  Errors          : {errors}")
    print()
    print("  Job type breakdown:")
    for jt, count in sorted(counters.items(), key=lambda x: -x[1]):
        label = JOB_TYPES.get(jt, jt)
        print(f"    {jt:<20}  {count:>4}  ({label})")
    print("=" * 55)


if __name__ == "__main__":
    main()
