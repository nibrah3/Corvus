"""Mark other_gig fallback jobs as enriched=TRUE so they leave the unenriched queue.

These jobs were processed by the gate (LLM call ran) but got the fallback
label when credits ran out. They're not truly unenriched — they've been
evaluated as far as possible. Setting enriched=TRUE prevents them from
being re-queued endlessly.

When OpenRouter/Anthropic credits are available, use:
  regate_existing.py --reclassify-fallback
to re-run the gate on them with proper LLM evaluation.
"""
import psycopg2, logging

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
DSN = "postgresql://corvus:corvus-local-password@127.0.0.1:5433/careerbridge"
conn = psycopg2.connect(DSN)
cur = conn.cursor()

# Mark other_gig fallback jobs as enriched — they've been through the gate
cur.execute("""
    UPDATE jobs SET enriched = TRUE
    WHERE job_type IS NOT NULL
    AND (enriched IS FALSE OR enriched IS NULL)
    AND status = 'pending'
""")
logging.info("Marked %d classified jobs as enriched", cur.rowcount)

# Also mark blocked jobs as enriched — they've been through the gate
cur.execute("""
    UPDATE jobs SET enriched = TRUE
    WHERE status = 'blocked'
    AND (enriched IS FALSE OR enriched IS NULL)
""")
logging.info("Marked %d blocked jobs as enriched", cur.rowcount)

conn.commit()

# Final counts
cur.execute("SELECT COUNT(*) FROM jobs WHERE enriched = TRUE")
logging.info("Total enriched: %d", cur.fetchone()[0])
cur.execute("SELECT COUNT(*) FROM jobs WHERE (enriched IS FALSE OR enriched IS NULL) AND status='pending'")
logging.info("Truly unenriched (not yet processed): %d", cur.fetchone()[0])

conn.close()
