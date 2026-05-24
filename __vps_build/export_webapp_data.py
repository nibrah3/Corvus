"""
export_webapp_data.py — VPS static JSON exporter for CareerBridge GitHub Pages.
Reads from local PostgreSQL (localhost:5432) and writes to /opt/corvus/webapp/data/*.json
Run via cron or on-demand after a discovery cycle.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
from datetime import datetime, date, timezone


# ── Load .env ──────────────────────────────────────────────────────────────────

def _load_env(path: str = "/opt/corvus/.env") -> None:
    try:
        with open(path) as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                key, _, val = line.partition("=")
                key = key.strip()
                val = val.strip().strip('"').strip("'")
                if key and key not in os.environ:
                    os.environ[key] = val
    except FileNotFoundError:
        pass

_load_env()


# ── Config ─────────────────────────────────────────────────────────────────────

DB_DSN  = os.environ.get("VPS_PG_DSN",
              "postgresql://corvus:corvus-local-password@localhost:5432/careerbridge")
OUT_DIR = os.environ.get("WEBAPP_DATA_DIR", "/opt/corvus/webapp/data")
os.makedirs(OUT_DIR, exist_ok=True)


# ── DB ─────────────────────────────────────────────────────────────────────────

try:
    import psycopg2
    import psycopg2.extras

    def get_db():
        return psycopg2.connect(DB_DSN, connect_timeout=10)

    def q(sql: str, params: tuple = ()) -> list[dict]:
        with get_db() as conn, conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute(sql, params)
            return cur.fetchall()

    HAS_DB = True
except Exception as e:
    print(f"[export] No DB: {e}", file=sys.stderr)
    HAS_DB = False


# ── JSON encoder ───────────────────────────────────────────────────────────────

class _Enc(json.JSONEncoder):
    def default(self, o):
        if isinstance(o, (datetime, date)):
            return o.isoformat()
        return super().default(o)


def write(name: str, data) -> None:
    path = os.path.join(OUT_DIR, f"{name}.json")
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, cls=_Enc, ensure_ascii=False, separators=(",", ":"))
    count = len(data) if isinstance(data, list) else 1
    print(f"[export] Wrote {name}.json: {count} record(s)")


# ── Export ─────────────────────────────────────────────────────────────────────

def export_all() -> None:
    if not HAS_DB:
        for name in ("jobs", "schools", "companies", "stats"):
            write(name, [] if name != "stats" else {"jobs": 0, "companies": 0, "schools": 0})
        return

    # Jobs — latest 500, ordered newest first
    rows = q("""
        SELECT title, company, url, sector, description, posted_at, created_at
        FROM jobs
        WHERE title IS NOT NULL
        ORDER BY id DESC LIMIT 500
    """)
    write("jobs", [dict(r) for r in rows])

    # Schools — best-matching first (criteria_score DESC), then alphabetical
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
        print(f"[export] schools failed: {e} — writing empty", file=sys.stderr)
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
    def cnt(sql: str) -> int:
        return int((q(sql) or [{}])[0].get("count", 0))

    stats = {
        "jobs":       cnt("SELECT COUNT(*) count FROM jobs"),
        "companies":  cnt("SELECT COUNT(*) count FROM discovered_platforms"),
        "schools":    cnt("SELECT COUNT(*) count FROM schools"),
        "channels":   cnt("SELECT COUNT(*) count FROM discovery_channels WHERE active=true"),
        "updated_at": datetime.now(timezone.utc).isoformat(),
    }
    write("stats", stats)
    print("[export] Export complete.")


# ── Optional git push ──────────────────────────────────────────────────────────

def git_push(repo_root: str = "/opt/corvus") -> None:
    """Stage webapp/data changes and push to GitHub Pages branch."""
    try:
        subprocess.run(
            ["git", "add", "webapp/data/"],
            cwd=repo_root, check=True, capture_output=True
        )
        result = subprocess.run(
            ["git", "diff", "--cached", "--quiet"],
            cwd=repo_root
        )
        if result.returncode == 0:
            print("[git] nothing to commit — data unchanged")
            return
        subprocess.run(
            ["git", "commit", "-m", f"data: auto-export {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}"],
            cwd=repo_root, check=True, capture_output=True
        )
        subprocess.run(
            ["git", "push"],
            cwd=repo_root, check=True, capture_output=True
        )
        print("[git] pushed webapp/data to GitHub")
    except subprocess.CalledProcessError as e:
        print(f"[git] push failed: {e.stderr.decode()[:200] if e.stderr else e}", file=sys.stderr)


if __name__ == "__main__":
    export_all()
    if "--push" in sys.argv:
        git_push()
