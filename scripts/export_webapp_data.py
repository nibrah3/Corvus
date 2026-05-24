"""
Export CareerBridge DB data to static JSON files for GitHub Pages.
Run on VPS via cron or on-demand. Writes to D:/cb-core/webapp/data/*.json
"""
import os, sys, json, logging
from datetime import datetime, date

sys.path.insert(0, os.path.dirname(__file__))
for line in open(os.path.join(os.path.dirname(__file__), "..", ".env")).read().splitlines():
    if "=" in line and not line.startswith("#"):
        k, _, v = line.partition("=")
        os.environ[k.strip()] = v.strip()

log = logging.getLogger("export_webapp")
logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")

OUT_DIR = os.path.join(os.path.dirname(__file__), "..", "webapp", "data")
os.makedirs(OUT_DIR, exist_ok=True)

try:
    import psycopg2, psycopg2.extras
    DB_URL = os.environ.get("VPS_PG_DSN", "postgresql://corvus:corvus-local-password@127.0.0.1:5433/careerbridge")
    def get_db(): return psycopg2.connect(DB_URL, connect_timeout=10)
    def q(sql, params=()):
        with get_db() as c, c.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute(sql, params); return cur.fetchall()
    HAS_DB = True
except Exception as e:
    log.warning("No DB: %s", e)
    HAS_DB = False

class _Enc(json.JSONEncoder):
    def default(self, o):
        if isinstance(o, (datetime, date)): return o.isoformat()
        return super().default(o)

def write(name: str, data):
    path = os.path.join(OUT_DIR, f"{name}.json")
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, cls=_Enc, ensure_ascii=False, separators=(",", ":"))
    log.info("Wrote %s: %d records", name, len(data) if isinstance(data, list) else 1)

def export_all():
    if not HAS_DB:
        # Write empty files so the web app doesn't error
        for name in ("jobs", "schools", "companies", "stats"):
            write(name, [] if name != "stats" else {"jobs":0,"companies":0,"schools":0})
        return

    # Jobs (latest 500)
    rows = q("""
        SELECT title, company, url, sector, description, posted_at, created_at
        FROM jobs
        WHERE title IS NOT NULL
        ORDER BY id DESC LIMIT 500
    """)
    write("jobs", [dict(r) for r in rows])

    # Schools — ordered by how many criteria each school meets (best first)
    try:
        school_rows = q("""
            SELECT name, url, enrollment_url, type, evidence,
                   no_id_verification, monthly_enrollment, instant_acceptance,
                   no_transcript_required, monthly_refund, community_college,
                   (no_id_verification::int + monthly_enrollment::int +
                    instant_acceptance::int + no_transcript_required::int +
                    monthly_refund::int + community_college::int) AS criteria_score,
                   created_at
            FROM schools
            ORDER BY criteria_score DESC, name
            LIMIT 500
        """)
        write("schools", [dict(r) for r in school_rows])
    except Exception as e:
        log.warning("Schools export: %s — writing empty", e)
        write("schools", [])

    # Companies
    co_rows = q("""
        SELECT company, careers_url, source, last_checked, ats_type
        FROM discovered_platforms
        WHERE careers_url IS NOT NULL
        ORDER BY id DESC LIMIT 500
    """)
    write("companies", [dict(r) for r in co_rows])

    # Stats
    def cnt(sql): return (q(sql) or [{}])[0].get("count", 0)
    stats = {
        "jobs":       int(cnt("SELECT COUNT(*) count FROM jobs")),
        "companies":  int(cnt("SELECT COUNT(*) count FROM discovered_platforms")),
        "schools":    int(cnt("SELECT COUNT(*) count FROM schools")),
        "channels":   int(cnt("SELECT COUNT(*) count FROM discovery_channels WHERE active=true")),
        "updated_at": datetime.utcnow().isoformat(),
    }
    write("stats", stats)

    log.info("Export complete.")

if __name__ == "__main__":
    export_all()
