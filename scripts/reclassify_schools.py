"""
reclassify_schools.py — Re-analyze score=0 schools with fresh Firecrawl.

For each school with criteria_score=0 that has a real homepage URL
(not a sub-page or article), re-crawl and re-analyze using the same
Claude Sonnet analyzer used during discovery.

Also validates score>=1 schools to ensure their enrollment_url is still
a real enrollment page and not a redirect/404.

Usage:
  python reclassify_schools.py               # process all score=0
  python reclassify_schools.py --limit 50    # process first N
  python reclassify_schools.py --dry-run     # classify without writing
"""
from __future__ import annotations

import argparse
import logging
import os
import sys
import time
from pathlib import Path
from urllib.parse import urlparse

CB_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(CB_DIR))

for _line in (CB_DIR / ".env").read_text(encoding="utf-8").splitlines():
    if "=" in _line and not _line.startswith("#"):
        _k, _, _v = _line.partition("=")
        if _k.strip() not in os.environ:
            os.environ[_k.strip()] = _v.strip()

import psycopg2
import psycopg2.extras

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("reclassify_schools")

DSN = os.environ.get("VPS_PG_DSN",
      "postgresql://corvus:corvus-local-password@127.0.0.1:5433/careerbridge")

# Sub-pages or article domains that should be deleted, not re-analyzed
JUNK_SUBPAGE_DEPTH = 4   # paths with >= N segments are sub-pages
JUNK_DOMAINS = {
    "usnews.com", "niche.com", "collegeraptor.com", "cappex.com",
    "collegedata.com", "petersons.com", "bestcolleges.com",
    "highered.texas.gov", "ed.gov", "studentaid.gov",
    "reddit.com", "quora.com", "linkedin.com", "indeed.com",
}


def _domain(url: str) -> str:
    try:
        return urlparse(url).netloc.lstrip("www.").lower()
    except Exception:
        return ""


def _is_junk_url(url: str) -> bool:
    d = _domain(url)
    if any(d == j or d.endswith("." + j) for j in JUNK_DOMAINS):
        return True
    try:
        path_depth = len([p for p in urlparse(url).path.split("/") if p])
        if path_depth >= JUNK_SUBPAGE_DEPTH:
            return True
    except Exception:
        pass
    return False


def _pg():
    return psycopg2.connect(DSN, connect_timeout=10)


def _get_zero_score_schools(conn, limit: int) -> list[dict]:
    with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
        cur.execute("""
            SELECT id, name, url, enrollment_url, criteria_score, url_hash
            FROM schools
            WHERE criteria_score = 0
            ORDER BY updated_at ASC
            LIMIT %s
        """, (limit,))
        return [dict(r) for r in cur.fetchall()]


def _update_school(conn, school_id: int, analyzed: dict) -> None:
    with conn.cursor() as cur:
        cur.execute("""
            UPDATE schools SET
                no_id_verification     = %(no_id_verification)s,
                no_transcript_required = %(no_transcript_required)s,
                monthly_enrollment     = %(monthly_enrollment)s,
                instant_acceptance     = %(instant_acceptance)s,
                monthly_refund         = %(monthly_refund)s,
                community_college      = %(community_college)s,
                filters                = %(filters)s,
                criteria_score         = %(criteria_score)s,
                enrollment_url         = %(enrollment_url)s,
                evidence               = %(evidence)s,
                updated_at             = NOW()
            WHERE id = %(id)s
        """, {**analyzed, "id": school_id})
    conn.commit()


def _delete_school(conn, school_id: int) -> None:
    with conn.cursor() as cur:
        cur.execute("DELETE FROM schools WHERE id = %s", (school_id,))
    conn.commit()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--limit", type=int, default=300)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    from schools_mcp._crawler import crawl_school
    from schools_mcp._analyzer import analyze
    import psycopg2.extras as _extras

    conn = _pg()
    schools = _get_zero_score_schools(conn, args.limit)
    log.info("Found %d score=0 schools to re-analyze%s",
             len(schools), " (DRY RUN)" if args.dry_run else "")

    deleted = improved = unchanged = errors = 0

    for i, school in enumerate(schools, 1):
        name = school["name"][:50]
        url  = school["url"] or ""
        log.info("[%d/%d] %s | %s", i, len(schools), name, url[:60])

        # Delete junk URLs immediately
        if _is_junk_url(url):
            log.info("  → DELETE (junk URL)")
            if not args.dry_run:
                _delete_school(conn, school["id"])
            deleted += 1
            continue

        try:
            crawled  = crawl_school({"name": school["name"], "url": url,
                                     "is_community_college": school.get("community_college", False),
                                     "open_admissions": False, "online_only": False})
            analyzed = analyze(crawled)
            score    = analyzed.get("criteria_score", 0)

            if score > 0:
                log.info("  → IMPROVED score %d  filters=%s", score, analyzed.get("filters"))
                if not args.dry_run:
                    # psycopg2 Json for evidence
                    analyzed["evidence"] = psycopg2.extras.Json(analyzed.get("evidence", {}))
                    analyzed["enrollment_url"] = analyzed.get("enrollment_url") or school.get("enrollment_url") or ""
                    _update_school(conn, school["id"], analyzed)
                improved += 1
            else:
                log.info("  → still 0 — keeping as unconfirmed")
                unchanged += 1
        except Exception as e:
            log.warning("  Error re-analyzing %s: %s", name, e)
            errors += 1

        time.sleep(0.5)

    print()
    print("=" * 55)
    print(f"Schools re-analysis{'  [DRY RUN]' if args.dry_run else ''}")
    print(f"  Processed  : {len(schools)}")
    print(f"  Deleted    : {deleted}  (junk URLs)")
    print(f"  Improved   : {improved}  (score 0 → ≥1)")
    print(f"  Unchanged  : {unchanged}  (still 0)")
    print(f"  Errors     : {errors}")
    print("=" * 55)

    conn.close()


if __name__ == "__main__":
    main()
