import psycopg2
DSN = "postgresql://corvus:corvus-local-password@127.0.0.1:5433/careerbridge"
conn = psycopg2.connect(DSN, connect_timeout=10)
cur = conn.cursor()
cur.execute("SELECT COUNT(*) FROM jobs")
print("jobs:", cur.fetchone()[0])
cur.execute("SELECT to_regclass('public.schools')")
print("schools table:", cur.fetchone()[0])
conn.close()
print("DB OK")
