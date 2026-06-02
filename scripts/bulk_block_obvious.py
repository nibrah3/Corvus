"""
bulk_block_obvious.py — Instant SQL-based blocking for jobs that are
100% certain non-gig-work without needing an LLM gate call.

Categories blocked without LLM (saving ~700 API calls):
  - source = 'us_schools'       -> school enrollment pages stored as jobs
  - url LIKE 'news.ycombinator' -> HN thread comments, not job listings
  - url LIKE 'reddit.com'       -> Reddit post links
  - Title starts 'Apply at'     -> Indeed-scraped school enrollment pages
"""
import psycopg2, logging

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
log = logging.getLogger("bulk_block")

DSN = "postgresql://corvus:corvus-local-password@127.0.0.1:5433/careerbridge"

RULES = [
    ("us_schools source",
     "source = 'us_schools'",
     "school_page_in_jobs_table"),

    ("HN comment URLs",
     "url LIKE '%%news.ycombinator.com%%'",
     "hn_comment_not_job"),

    ("Reddit post URLs",
     "url LIKE '%%reddit.com%%' AND source = 'reddit'",
     "reddit_post_not_job"),

    ("Indeed school enrollment pages",
     "url LIKE '%%indeed.com%%' AND (title ILIKE 'apply at%%' OR title ILIKE 'open enrollment%%')",
     "school_enrollment_page"),

    ("HN jobs page (not individual listing)",
     "url LIKE '%%ycombinator.com/jobs%%'",
     "hn_jobs_page_not_listing"),
]

def run():
    conn = psycopg2.connect(DSN, connect_timeout=10)
    cur = conn.cursor()
    total = 0

    for name, where_clause, reason in RULES:
        cur.execute(
            f"""
            UPDATE jobs
            SET status = 'blocked',
                quality_issue = %s
            WHERE ({where_clause})
              AND status NOT IN ('blocked', 'completed', 'applied')
            """,
            (reason,),
        )
        n = cur.rowcount
        log.info("Blocked %4d  [%s]", n, name)
        total += n

    conn.commit()
    conn.close()
    log.info("Total bulk-blocked: %d", total)
    return total

if __name__ == "__main__":
    run()
