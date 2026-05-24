"""
vps_mcp — Desktop bridge to VPS pipeline.
Runs on Desktop at port 8713.
Connects to VPS via SSH tunnels:
  Redis:    localhost:6380 -> VPS:6379
  Postgres: localhost:5433 -> VPS:5432
  Crawlee:  localhost:3101 -> VPS:3100
Start tunnels first: powershell D:\\cb-core\\scripts\\vps_tunnel.ps1
"""
import sys
import os
import json
import urllib.request
import urllib.error
import socket

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from _minmcp import MinMCP

# Tunnel endpoints (SSH forward from Desktop)
REDIS_HOST = os.environ.get("VPS_REDIS_HOST", "127.0.0.1")
REDIS_PORT = int(os.environ.get("VPS_REDIS_PORT", "6380"))
PG_DSN     = os.environ.get("VPS_PG_DSN", "postgresql://corvus:corvus-local-password@127.0.0.1:5433/careerbridge")
CRAWLEE    = os.environ.get("VPS_CRAWLEE_URL", "http://127.0.0.1:3101")

mcp = MinMCP("vps_mcp")


# ── Redis helpers ──────────────────────────────────────────────────────────────

def _redis_cmd(*parts: str) -> str:
    """Send a raw RESP command to Redis and return the reply as a string."""
    with socket.create_connection((REDIS_HOST, REDIS_PORT), timeout=5) as sock:
        cmd = f"*{len(parts)}\r\n" + "".join(f"${len(p)}\r\n{p}\r\n" for p in parts)
        sock.sendall(cmd.encode())
        data = b""
        while True:
            chunk = sock.recv(4096)
            if not chunk:
                break
            data += chunk
            if data.endswith(b"\r\n"):
                break
        return data.decode(errors="replace").strip()


def _redis_lrange(key: str, start: int = 0, end: int = -1) -> list[str]:
    try:
        reply = _redis_cmd("LRANGE", key, str(start), str(end))
        # Parse RESP array: *N\r\n$len\r\nval\r\n...
        lines = reply.split("\r\n")
        results = []
        i = 0
        if lines[i].startswith("*"):
            count = int(lines[i][1:])
            i += 1
            for _ in range(count):
                if lines[i].startswith("$"):
                    length = int(lines[i][1:])
                    i += 1
                    if length >= 0:
                        results.append(lines[i])
                    i += 1
        return results
    except Exception as e:
        return []


def _redis_rpush(key: str, value: str) -> bool:
    try:
        _redis_cmd("RPUSH", key, value)
        return True
    except Exception:
        return False


def _redis_lrem(key: str, value: str) -> bool:
    try:
        _redis_cmd("LREM", key, "1", value)
        return True
    except Exception:
        return False


def _redis_get(key: str) -> str | None:
    try:
        reply = _redis_cmd("GET", key)
        if reply.startswith("$-1"):
            return None
        lines = reply.split("\r\n")
        if lines[0].startswith("$"):
            return lines[1] if len(lines) > 1 else None
        return None
    except Exception:
        return None


def _redis_setex(key: str, seconds: int, value: str) -> bool:
    try:
        _redis_cmd("SETEX", key, str(seconds), value)
        return True
    except Exception:
        return False


def _redis_keys(pattern: str) -> list[str]:
    try:
        reply = _redis_cmd("KEYS", pattern)
        lines = reply.split("\r\n")
        results = []
        i = 0
        if not lines or not lines[i].startswith("*"):
            return results
        count = int(lines[i][1:])
        i += 1
        for _ in range(count):
            if i >= len(lines):
                break
            if lines[i].startswith("$"):
                i += 1
                if i < len(lines):
                    results.append(lines[i])
                i += 1
        return results
    except Exception:
        return []


# ── Postgres helpers ───────────────────────────────────────────────────────────

def _pg():
    import psycopg2
    import psycopg2.extras
    c = psycopg2.connect(PG_DSN)
    c.autocommit = True
    return c


def _ts(v):
    return v.isoformat() if hasattr(v, "isoformat") else v


def _row_to_dict(row) -> dict:
    return {k: _ts(v) for k, v in dict(row).items()}


# ── Job tools ─────────────────────────────────────────────────────────────────

@mcp.tool()
def get_pending_approvals(limit: int = 10) -> dict:
    """Get jobs waiting for Mike's approval from Redis pending queue."""
    items = _redis_lrange("corvus:pending_approvals", 0, limit - 1)
    parsed = []
    for item in items:
        try:
            parsed.append(json.loads(item))
        except Exception:
            parsed.append({"raw": item})
    return {"count": len(parsed), "jobs": parsed}


@mcp.tool()
def approve_job(job_id: int) -> dict:
    """Approve a job: mark postgres status='approved' and push to Redis corvus:approved_jobs."""
    try:
        conn = _pg()
        cur = conn.cursor(cursor_factory=__import__("psycopg2.extras", fromlist=["RealDictCursor"]).RealDictCursor)
        cur.execute(
            "UPDATE jobs SET status='approved', approved_at=NOW() WHERE id=%s "
            "RETURNING id, url, title, company, profile_id",
            (job_id,)
        )
        row = cur.fetchone()
        if not row:
            return {"error": f"Job {job_id} not found"}
        payload = json.dumps({
            "job_id":     job_id,
            "url":        row["url"],
            "title":      row.get("title") or "",
            "company":    row.get("company") or "",
            "profile_id": row.get("profile_id") or "",
        })
        _redis_rpush("corvus:approved_jobs", payload)
        # Remove from pending approvals if present
        pending = _redis_lrange("corvus:pending_approvals", 0, -1)
        for item in pending:
            try:
                if json.loads(item).get("job_id") == job_id:
                    _redis_lrem("corvus:pending_approvals", item)
            except Exception:
                pass
        return {"ok": True, "job_id": job_id, "status": "approved"}
    except Exception as e:
        return {"error": str(e)}


@mcp.tool()
def skip_job(job_id: int) -> dict:
    """Skip a job: mark postgres status='skipped' and push to Redis corvus:skipped_jobs."""
    try:
        conn = _pg()
        cur = conn.cursor()
        cur.execute("UPDATE jobs SET status='skipped' WHERE id=%s", (job_id,))
        if cur.rowcount == 0:
            return {"error": f"Job {job_id} not found"}
        _redis_rpush("corvus:skipped_jobs", json.dumps({"job_id": job_id}))
        # Remove from pending approvals
        pending = _redis_lrange("corvus:pending_approvals", 0, -1)
        for item in pending:
            try:
                if json.loads(item).get("job_id") == job_id:
                    _redis_lrem("corvus:pending_approvals", item)
            except Exception:
                pass
        return {"ok": True, "job_id": job_id, "status": "skipped"}
    except Exception as e:
        return {"error": str(e)}


@mcp.tool()
def list_jobs(status: str = "", limit: int = 20) -> dict:
    """List jobs from VPS postgres, optionally filtered by status."""
    try:
        conn = _pg()
        cur = conn.cursor(cursor_factory=__import__("psycopg2.extras", fromlist=["RealDictCursor"]).RealDictCursor)
        if status:
            cur.execute("SELECT * FROM jobs WHERE status=%s ORDER BY discovered_at DESC LIMIT %s", (status, limit))
        else:
            cur.execute("SELECT * FROM jobs ORDER BY discovered_at DESC LIMIT %s", (limit,))
        rows = [_row_to_dict(r) for r in cur.fetchall()]
        return {"jobs": rows, "count": len(rows)}
    except Exception as e:
        return {"error": str(e)}


@mcp.tool()
def get_job(job_id: int) -> dict:
    """Get full job record from VPS postgres."""
    try:
        conn = _pg()
        cur = conn.cursor(cursor_factory=__import__("psycopg2.extras", fromlist=["RealDictCursor"]).RealDictCursor)
        cur.execute("SELECT * FROM jobs WHERE id=%s", (job_id,))
        row = cur.fetchone()
        if not row:
            return {"error": f"Job {job_id} not found"}
        return _row_to_dict(row)
    except Exception as e:
        return {"error": str(e)}


@mcp.tool()
def upsert_job(
    url: str,
    title: str = "",
    company: str = "",
    description: str = "",
    score: float = 0.0,
    source: str = "manual",
    profile_id: str = ""
) -> dict:
    """Insert or update a job in VPS postgres (used for manually submitted jobs)."""
    try:
        conn = _pg()
        cur = conn.cursor()
        cur.execute(
            """
            INSERT INTO jobs (url, title, company, description, score, source, profile_id)
            VALUES (%s,%s,%s,%s,%s,%s,%s)
            ON CONFLICT (url) DO UPDATE SET
                title=EXCLUDED.title, company=EXCLUDED.company,
                description=EXCLUDED.description, score=EXCLUDED.score,
                source=EXCLUDED.source, profile_id=EXCLUDED.profile_id
            RETURNING id
            """,
            (url, title, company, description, score, source, profile_id or None)
        )
        job_id = cur.fetchone()[0]
        return {"job_id": job_id, "url": url}
    except Exception as e:
        return {"error": str(e)}


@mcp.tool()
def update_job_status(job_id: int, status: str, result: str = "") -> dict:
    """Update a job's status in VPS postgres (called after assessment completes)."""
    try:
        conn = _pg()
        cur = conn.cursor()
        if result:
            cur.execute("UPDATE jobs SET status=%s, result=%s WHERE id=%s", (status, result, job_id))
        else:
            cur.execute("UPDATE jobs SET status=%s WHERE id=%s", (status, job_id))
        if cur.rowcount == 0:
            return {"error": f"Job {job_id} not found"}
        return {"ok": True, "job_id": job_id, "status": status}
    except Exception as e:
        return {"error": str(e)}


# ── Profile tools ──────────────────────────────────────────────────────────────

@mcp.tool()
def list_profiles() -> dict:
    """List all candidate profiles stored on VPS."""
    try:
        conn = _pg()
        cur = conn.cursor(cursor_factory=__import__("psycopg2.extras", fromlist=["RealDictCursor"]).RealDictCursor)
        cur.execute("SELECT id, name, email FROM profiles ORDER BY name")
        rows = [_row_to_dict(r) for r in cur.fetchall()]
        return {"profiles": rows, "count": len(rows)}
    except Exception as e:
        return {"error": str(e)}


@mcp.tool()
def get_profile(profile_id: str) -> dict:
    """Get a full candidate profile from VPS postgres."""
    try:
        conn = _pg()
        cur = conn.cursor(cursor_factory=__import__("psycopg2.extras", fromlist=["RealDictCursor"]).RealDictCursor)
        cur.execute("SELECT * FROM profiles WHERE id=%s", (profile_id,))
        row = cur.fetchone()
        if not row:
            return {"error": f"Profile {profile_id} not found"}
        return _row_to_dict(row)
    except Exception as e:
        return {"error": str(e)}


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
    response_bias: str = "",
    imap_password: str = "",
    imap_server: str = "imap.gmail.com",
    imap_port: int = 993
) -> dict:
    """Create or update a candidate profile on VPS postgres (including IMAP credentials)."""
    try:
        conn = _pg()
        cur = conn.cursor()
        cur.execute(
            """
            INSERT INTO profiles
                (id, name, email, phone, location, bio, skills, experience,
                 education, big_five, response_bias,
                 imap_password, imap_server, imap_port, updated_at)
            VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s, NOW())
            ON CONFLICT (id) DO UPDATE SET
                name=EXCLUDED.name, email=EXCLUDED.email, phone=EXCLUDED.phone,
                location=EXCLUDED.location, bio=EXCLUDED.bio, skills=EXCLUDED.skills,
                experience=EXCLUDED.experience, education=EXCLUDED.education,
                big_five=EXCLUDED.big_five, response_bias=EXCLUDED.response_bias,
                imap_password=COALESCE(NULLIF(EXCLUDED.imap_password,''), profiles.imap_password),
                imap_server=COALESCE(NULLIF(EXCLUDED.imap_server,''), profiles.imap_server),
                imap_port=EXCLUDED.imap_port,
                updated_at=NOW()
            """,
            (id, name, email, phone, location, bio, skills, experience,
             education, big_five, response_bias, imap_password, imap_server, imap_port)
        )
        return {"ok": True, "profile_id": id}
    except Exception as e:
        return {"error": str(e)}


# ── Discovery tools ────────────────────────────────────────────────────────────

@mcp.tool()
def trigger_discovery(source: str = "all", keywords: str = "") -> dict:
    """Trigger a VPS discovery scrape via the Crawlee API (via SSH tunnel on port 3101)."""
    url = f"{CRAWLEE}/scrape/{source}"
    body = json.dumps({"keywords": keywords, "limit": 50}).encode()
    req = urllib.request.Request(url, data=body, headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            return json.loads(resp.read().decode())
    except Exception as e:
        return {"error": str(e), "url": url}


@mcp.tool()
def get_system_status() -> dict:
    """Get a quick status snapshot: pending approvals count, approved jobs count, Redis ping."""
    status = {}
    try:
        pending = _redis_lrange("corvus:pending_approvals", 0, -1)
        approved = _redis_lrange("corvus:approved_jobs", 0, -1)
        status["pending_approvals"] = len(pending)
        status["approved_jobs"] = len(approved)
        status["redis"] = "ok"
    except Exception as e:
        status["redis"] = f"error: {e}"

    try:
        conn = _pg()
        cur = conn.cursor()
        cur.execute("SELECT status, count(*) FROM jobs GROUP BY status")
        status["jobs_by_status"] = {row[0]: row[1] for row in cur.fetchall()}
        status["postgres"] = "ok"
    except Exception as e:
        status["postgres"] = f"error: {e}"

    return status


# ── Node tools ────────────────────────────────────────────────────────────────

@mcp.tool()
def list_nodes() -> dict:
    """List all execution nodes that sent a heartbeat in the last 90 seconds."""
    import time
    keys = [k for k in _redis_keys("corvus:node:*") if k.count(":") == 2]
    nodes = []
    now = int(time.time())
    for key in keys:
        raw = _redis_get(key)
        if raw:
            try:
                info = json.loads(raw)
                info["seconds_ago"] = now - info.get("last_seen", now)
                nodes.append(info)
            except Exception:
                nodes.append({"node_id": key.split(":")[-1], "raw": raw})
    return {"nodes": nodes, "count": len(nodes)}


@mcp.tool()
def register_node(node_id: str, hostname: str, capabilities: str = "full", ttl: int = 90) -> dict:
    """Register or refresh a node heartbeat. Called by node_agent.py every 30 s."""
    import time
    payload = json.dumps({
        "node_id":      node_id,
        "hostname":     hostname,
        "capabilities": capabilities,
        "last_seen":    int(time.time()),
    })
    ok = _redis_setex(f"corvus:node:{node_id}", ttl, payload)
    return {"ok": ok, "node_id": node_id, "ttl": ttl}


@mcp.tool()
def dispatch_job_to_node(job_id: int, node_id: str) -> dict:
    """Approve a job and send it to a specific remote execution node's task queue."""
    try:
        conn = _pg()
        cur = conn.cursor(cursor_factory=__import__("psycopg2.extras", fromlist=["RealDictCursor"]).RealDictCursor)
        cur.execute(
            "UPDATE jobs SET status='approved', approved_at=NOW() "
            "WHERE id=%s RETURNING id, url, title, company, profile_id",
            (job_id,)
        )
        row = cur.fetchone()
        if not row:
            return {"error": f"Job {job_id} not found"}
        payload = json.dumps({
            "job_id":     job_id,
            "url":        row["url"],
            "title":      row.get("title") or "",
            "company":    row.get("company") or "",
            "profile_id": row.get("profile_id") or "",
            "node_id":    node_id,
        })
        queue_key = f"corvus:node:{node_id}:tasks"
        _redis_rpush(queue_key, payload)
        # Remove from pending approvals
        pending = _redis_lrange("corvus:pending_approvals", 0, -1)
        for item in pending:
            try:
                if json.loads(item).get("job_id") == job_id:
                    _redis_lrem("corvus:pending_approvals", item)
            except Exception:
                pass
        return {"ok": True, "job_id": job_id, "node_id": node_id, "queue": queue_key}
    except Exception as e:
        return {"error": str(e)}


if __name__ == "__main__":
    mcp.run()
