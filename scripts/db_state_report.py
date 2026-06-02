"""Final DB state report."""
import psycopg2, psycopg2.extras
from collections import Counter

DSN = "postgresql://corvus:corvus-local-password@127.0.0.1:5433/careerbridge"
conn = psycopg2.connect(DSN, connect_timeout=8)
cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)

print("=" * 60)
print("JOBS")
print("=" * 60)

cur.execute("SELECT COUNT(*) n FROM jobs")
print(f"Total: {cur.fetchone()['n']}")

cur.execute("SELECT status, COUNT(*) n FROM jobs GROUP BY status ORDER BY n DESC")
print("By status:", {r['status']: r['n'] for r in cur.fetchall()})

cur.execute("SELECT job_type, COUNT(*) n FROM jobs WHERE job_type IS NOT NULL GROUP BY job_type ORDER BY n DESC")
jt = cur.fetchall()
print(f"\nClassified (job_type set): {sum(r['n'] for r in jt)}")
for r in jt:
    print(f"  {r['job_type']:<25} {r['n']}")

cur.execute("SELECT COUNT(*) n FROM jobs WHERE job_type IS NULL AND status='pending'")
print(f"\nStill needs gate (pending + no job_type): {cur.fetchone()['n']}")

cur.execute("SELECT COUNT(*) n FROM jobs WHERE status='blocked'")
print(f"Blocked total: {cur.fetchone()['n']}")

cur.execute("""
    SELECT quality_issue, COUNT(*) n FROM jobs
    WHERE status='blocked'
    GROUP BY quality_issue ORDER BY n DESC LIMIT 10
""")
print("Block reasons:")
for r in cur.fetchall():
    print(f"  {(r['quality_issue'] or 'none'):<35} {r['n']}")

print()
print("=" * 60)
print("SCHOOLS")
print("=" * 60)

cur.execute("SELECT COUNT(*) n FROM schools")
print(f"Total: {cur.fetchone()['n']}")

cur.execute("SELECT criteria_score, COUNT(*) n FROM schools GROUP BY criteria_score ORDER BY criteria_score DESC")
print("By score:")
for r in cur.fetchall():
    label = {4:"strong",3:"good",2:"partial",1:"weak",0:"unconfirmed"}.get(r['criteria_score'],'?')
    print(f"  score={r['criteria_score']} ({label:<12}): {r['n']}")

cur.execute("SELECT COUNT(*) n FROM schools WHERE criteria_score >= 1")
print(f"\nUsable (score>=1): {cur.fetchone()['n']}")
cur.execute("SELECT COUNT(*) n FROM schools WHERE source_url IS NOT NULL")
print(f"With source_url:  {cur.fetchone()['n']}")

conn.close()
