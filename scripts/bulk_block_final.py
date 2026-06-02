"""Final bulk-block pass — professional jobs and all remaining aggregator patterns."""
import psycopg2, logging

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
log = logging.getLogger("bulk_block_final")

DSN = "postgresql://corvus:corvus-local-password@127.0.0.1:5433/careerbridge"
conn = psycopg2.connect(DSN)
cur = conn.cursor()

# 1. Block specific professional jobs identified in gate review
professional_ids = [163281, 163280, 163274, 163264, 163263, 163284, 163283]
cur.execute(
    "UPDATE jobs SET status='blocked', quality_issue='professional_job' "
    "WHERE id = ANY(%s) AND status NOT IN ('blocked','completed','applied')",
    (professional_ids,)
)
log.info("Blocked %d identified professional jobs", cur.rowcount)

# 2. Block all remaining aggregator search pages with comprehensive patterns
cur.execute("""
    UPDATE jobs
    SET status = 'blocked', quality_issue = 'aggregator_search_page'
    WHERE status NOT IN ('blocked','completed','applied','skipped','failed','error','partial')
    AND (
        url ~ 'indeed\\.com/q-[a-z0-9%,._-]+-jobs\\.html'
        OR url ~ 'ziprecruiter\\.com/Jobs/[A-Za-z0-9%-]+'
        OR url ~ 'simplyhired\\.com/(q-[a-z0-9-]+-jobs\\.html|search\\?)'
        OR url ~ 'glassdoor\\.com/Job/[a-z0-9-]+-jobs-'
        OR (url ~ 'indeed\\.com/q-' AND url LIKE '%jobs%')
    )
""")
log.info("Blocked %d additional aggregator search pages", cur.rowcount)

# 3. Block corporate career page homepages that are not actual listings
cur.execute("""
    UPDATE jobs
    SET status = 'blocked', quality_issue = 'corporate_career_homepage'
    WHERE status NOT IN ('blocked','completed','applied','skipped','failed','error','partial')
    AND (
        url LIKE '%/careers' OR url LIKE '%/careers/'
        OR url LIKE '%/jobs' OR url LIKE '%/jobs/'
        OR url LIKE '%/work-with-us' OR url LIKE '%/work-with-us/'
    )
    AND (title ILIKE 'apply at%%' OR title = '' OR title IS NULL)
    AND source NOT IN ('appen','heartex','prolific','toloka','remotasks')
""")
log.info("Blocked %d corporate career homepages (no specific listing)", cur.rowcount)

conn.commit()

# Show final state
cur.execute("SELECT status, COUNT(*) n FROM jobs GROUP BY status ORDER BY n DESC")
print("\nFinal job status distribution:")
for r in cur.fetchall():
    print(f"  {r[0]:<12} {r[1]}")

cur.execute("""
    SELECT COUNT(*) FROM jobs
    WHERE (enriched IS FALSE OR enriched IS NULL)
    AND status NOT IN ('blocked','completed','applied','skipped','failed','error','partial')
""")
print(f"\nRemaining unenriched (not blocked): {cur.fetchone()[0]}")

conn.close()
