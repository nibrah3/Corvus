import sys
import os
import json

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from _minmcp import MinMCP

import psycopg2
import psycopg2.extras

DSN = os.environ.get(
    "POSTGRES_DSN",
    "postgresql://corvus:corvus-local-password@localhost:5432/careerbridge"
)

mcp = MinMCP("postgres_mcp")


def _conn():
    c = psycopg2.connect(DSN)
    c.autocommit = True
    return c


@mcp.tool()
def list_jobs(status: str = "", limit: int = 20) -> dict:
    """List jobs, optionally filtered by status."""
    with _conn() as conn:
        cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
        if status:
            cur.execute(
                "SELECT * FROM jobs WHERE status=%s ORDER BY discovered_at DESC LIMIT %s",
                (status, limit)
            )
        else:
            cur.execute(
                "SELECT * FROM jobs ORDER BY discovered_at DESC LIMIT %s",
                (limit,)
            )
        rows = [dict(r) for r in cur.fetchall()]
        for r in rows:
            for k, v in r.items():
                if hasattr(v, "isoformat"):
                    r[k] = v.isoformat()
    return {"jobs": rows, "count": len(rows)}


@mcp.tool()
def get_job(job_id: int) -> dict:
    """Get a full job record by ID."""
    with _conn() as conn:
        cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
        cur.execute("SELECT * FROM jobs WHERE id=%s", (job_id,))
        row = cur.fetchone()
        if not row:
            return {"error": f"Job {job_id} not found"}
        r = dict(row)
        for k, v in r.items():
            if hasattr(v, "isoformat"):
                r[k] = v.isoformat()
    return r


@mcp.tool()
def upsert_job(
    url: str,
    title: str = "",
    company: str = "",
    description: str = "",
    score: float = 0.0,
    source: str = "discovered",
    profile_id: str = ""
) -> dict:
    """Insert or update a job record. Returns the job ID."""
    with _conn() as conn:
        cur = conn.cursor()
        cur.execute(
            """
            INSERT INTO jobs (url, title, company, description, score, source, profile_id)
            VALUES (%s, %s, %s, %s, %s, %s, %s)
            ON CONFLICT (url) DO UPDATE SET
                title = EXCLUDED.title,
                company = EXCLUDED.company,
                description = EXCLUDED.description,
                score = EXCLUDED.score,
                source = EXCLUDED.source,
                profile_id = EXCLUDED.profile_id
            RETURNING id
            """,
            (url, title, company, description, score, source, profile_id or None)
        )
        job_id = cur.fetchone()[0]
    return {"job_id": job_id, "url": url}


@mcp.tool()
def update_job_status(job_id: int, status: str, result: str = "") -> dict:
    """Update the status (and optional result JSON) of a job."""
    with _conn() as conn:
        cur = conn.cursor()
        if result:
            cur.execute(
                "UPDATE jobs SET status=%s, result=%s WHERE id=%s",
                (status, result, job_id)
            )
        else:
            cur.execute("UPDATE jobs SET status=%s WHERE id=%s", (status, job_id))
        if cur.rowcount == 0:
            return {"error": f"Job {job_id} not found"}
    return {"job_id": job_id, "status": status}


@mcp.tool()
def list_profiles() -> dict:
    """List all profiles (id and name only)."""
    with _conn() as conn:
        cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
        cur.execute("SELECT id, name, email FROM profiles ORDER BY name")
        rows = [dict(r) for r in cur.fetchall()]
    return {"profiles": rows, "count": len(rows)}


@mcp.tool()
def get_profile(profile_id: str) -> dict:
    """Get a full profile record."""
    with _conn() as conn:
        cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
        cur.execute("SELECT * FROM profiles WHERE id=%s", (profile_id,))
        row = cur.fetchone()
        if not row:
            return {"error": f"Profile {profile_id} not found"}
        r = dict(row)
        for k, v in r.items():
            if hasattr(v, "isoformat"):
                r[k] = v.isoformat()
    return r


@mcp.tool()
def upsert_profile(
    id: str,
    name: str,
    email: str = "",
    phone: str = "",
    location: str = "",
    bio: str = "",
    skills: str = "",
    experience: str = "",
    education: str = "",
    big_five: str = "",
    response_bias: str = ""
) -> dict:
    """Insert or update a candidate profile."""
    with _conn() as conn:
        cur = conn.cursor()
        cur.execute(
            """
            INSERT INTO profiles
                (id, name, email, phone, location, bio, skills, experience,
                 education, big_five, response_bias, updated_at)
            VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s, NOW())
            ON CONFLICT (id) DO UPDATE SET
                name=EXCLUDED.name, email=EXCLUDED.email, phone=EXCLUDED.phone,
                location=EXCLUDED.location, bio=EXCLUDED.bio, skills=EXCLUDED.skills,
                experience=EXCLUDED.experience, education=EXCLUDED.education,
                big_five=EXCLUDED.big_five, response_bias=EXCLUDED.response_bias,
                updated_at=NOW()
            """,
            (id, name, email, phone, location, bio, skills, experience,
             education, big_five, response_bias)
        )
    return {"profile_id": id}


@mcp.tool()
def create_application(job_id: int, profile_id: str) -> dict:
    """Create a new application record."""
    with _conn() as conn:
        cur = conn.cursor()
        cur.execute(
            "INSERT INTO applications (job_id, profile_id) VALUES (%s, %s) RETURNING id",
            (job_id, profile_id)
        )
        app_id = cur.fetchone()[0]
    return {"application_id": app_id, "job_id": job_id, "profile_id": profile_id}


@mcp.tool()
def update_application(app_id: int, status: str, result: str = "") -> dict:
    """Update the status and optional JSON result of an application."""
    with _conn() as conn:
        cur = conn.cursor()
        cur.execute(
            "UPDATE applications SET status=%s, assessment_result=%s, updated_at=NOW() WHERE id=%s",
            (status, result or None, app_id)
        )
        if cur.rowcount == 0:
            return {"error": f"Application {app_id} not found"}
    return {"application_id": app_id, "status": status}


@mcp.tool()
def log_event(type: str, payload: str = "") -> dict:
    """Write a system event log entry."""
    with _conn() as conn:
        cur = conn.cursor()
        cur.execute(
            "INSERT INTO events (type, payload) VALUES (%s, %s) RETURNING id",
            (type, payload or None)
        )
        event_id = cur.fetchone()[0]
    return {"event_id": event_id, "type": type}


if __name__ == "__main__":
    mcp.run()
