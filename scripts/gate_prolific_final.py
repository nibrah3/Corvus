"""Final pass: classify all remaining Prolific AI Training roles."""
import psycopg2, logging

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
DSN = "postgresql://corvus:corvus-local-password@127.0.0.1:5433/careerbridge"
conn = psycopg2.connect(DSN)
cur = conn.cursor()

# All remaining Prolific domain-expert AI training tasks
cur.execute("""
    UPDATE jobs SET job_type='ai_training', enriched=TRUE
    WHERE (enriched IS FALSE OR enriched IS NULL)
    AND job_type IS NULL
    AND status NOT IN ('blocked','skipped','completed','failed','error','partial','applied')
    AND url LIKE '%%prolific%%'
    AND (title ILIKE '%%AI Train%%' OR title ILIKE '%%AI Trainer%%')
""")
logging.info("Kept %d Prolific AI Training domain-expert roles as ai_training", cur.rowcount)

# Check for any non-Prolific stragglers
cur2 = conn.cursor()
cur2.execute("""
    SELECT id, url, title, source FROM jobs
    WHERE (enriched IS FALSE OR enriched IS NULL)
    AND job_type IS NULL
    AND status NOT IN ('blocked','skipped','completed','failed','error','partial','applied')
    AND url NOT LIKE '%%prolific%%'
    ORDER BY id ASC
    LIMIT 30
""")
others = cur2.fetchall()
if others:
    logging.info("Non-Prolific remaining (%d):", len(others))
    for r in others:
        logging.info("  [%d] %s | %s", r[0], (r[2] or "")[:50], r[1][:60])
else:
    logging.info("All non-Prolific jobs processed!")

# Grand total
cur3 = conn.cursor()
cur3.execute("""
    SELECT COUNT(*) FROM jobs
    WHERE (enriched IS FALSE OR enriched IS NULL)
    AND job_type IS NULL
    AND status NOT IN ('blocked','skipped','completed','failed','error','partial','applied')
""")
remaining = cur3.fetchone()[0]
logging.info("Total truly unenriched remaining: %d", remaining)

conn.commit()
conn.close()
