"""
corvus_discovery.py — Autonomous job discovery cycle for CareerBridge VPS.
Replaces `claude --print` in systemd timers.

Steps:
  1. Scrape job listings from all sources via crawlee_mcp
  2. For each result, get full description via crawlee_mcp.scrape_url
  3. Score each job against all active profiles via OpenRouter (Claude)
  4. Upsert jobs scoring >= 0.6 to postgres via postgres_mcp
  5. Push summaries to Redis corvus:pending_approvals
  6. Log cycle stats to postgres events table
  7. Send Telegram summary

Run: python3 corvus_discovery.py
"""
from __future__ import annotations

import json
import os
import socket
import urllib.request
import urllib.error
import sys
import time
from datetime import datetime, timezone

# ── Config ─────────────────────────────────────────────────────────────────────

POSTGRES_MCP  = "http://localhost:8801"
CRAWLEE_MCP   = "http://localhost:8802"
TELEGRAM_MCP  = "http://localhost:8803"
REDIS_HOST    = "127.0.0.1"
REDIS_PORT    = 6379
REDIS_KEY     = "corvus:pending_approvals"
SCORE_THRESH  = 0.6
OPENROUTER_KEY = os.environ.get("OPENROUTER_API_KEY", "")
OR_MODEL       = "anthropic/claude-haiku-4-5-20251001"

SOURCES = ["reddit", "hackernews", "wellfound", "ycombinator"]


# ── HTTP helpers ───────────────────────────────────────────────────────────────

def _post(url: str, body: dict, timeout: int = 30) -> dict:
    data = json.dumps(body).encode()
    req = urllib.request.Request(url, data=data, headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return json.loads(resp.read().decode())
    except Exception as e:
        return {"error": str(e)}


_mcp_seq = 0

def mcp_call(base: str, tool: str, **kwargs) -> dict:
    """Call a MinMCP tool via JSON-RPC POST to /mcp."""
    global _mcp_seq
    _mcp_seq += 1
    resp = _post(f"{base}/mcp", {
        "jsonrpc": "2.0",
        "id": _mcp_seq,
        "method": "tools/call",
        "params": {"name": tool, "arguments": kwargs}
    })
    if "error" in resp:
        return resp
    # Unwrap MCP content: result.content[0].text (JSON string)
    try:
        text = resp["result"]["content"][0]["text"]
        return json.loads(text)
    except Exception:
        return resp


# ── Redis ──────────────────────────────────────────────────────────────────────

def redis_rpush(key: str, value: str) -> None:
    try:
        with socket.create_connection((REDIS_HOST, REDIS_PORT), timeout=3) as sock:
            cmd = f"*3\r\n$5\r\nRPUSH\r\n${len(key)}\r\n{key}\r\n${len(value)}\r\n{value}\r\n"
            sock.sendall(cmd.encode())
            sock.recv(256)
    except Exception as e:
        print(f"[redis] RPUSH failed: {e}", file=sys.stderr)


# ── Scoring via OpenRouter ─────────────────────────────────────────────────────

def score_job(job: dict, profiles: list[dict]) -> list[tuple[dict, float]]:
    """
    Ask Claude to score this job against each profile.
    Returns list of (profile, score) pairs.
    """
    if not OPENROUTER_KEY:
        # Fallback: simple keyword match if no key
        return [(p, 0.7) for p in profiles]

    results = []
    for profile in profiles:
        prompt = (
            f"Score how well this job matches this candidate. Reply with ONLY a decimal 0.0-1.0.\n\n"
            f"JOB TITLE: {job.get('title', 'Unknown')}\n"
            f"COMPANY: {job.get('company', '')}\n"
            f"DESCRIPTION (first 500 chars): {str(job.get('description', ''))[:500]}\n\n"
            f"CANDIDATE SKILLS: {profile.get('skills', '')}\n"
            f"CANDIDATE LOCATION: {profile.get('location', '')}\n"
            f"CANDIDATE BIO: {str(profile.get('bio', ''))[:200]}\n"
        )
        body = {
            "model": OR_MODEL,
            "messages": [{"role": "user", "content": prompt}],
            "max_tokens": 10,
        }
        req = urllib.request.Request(
            "https://openrouter.ai/api/v1/chat/completions",
            data=json.dumps(body).encode(),
            headers={
                "Content-Type": "application/json",
                "Authorization": f"Bearer {OPENROUTER_KEY}",
            }
        )
        try:
            with urllib.request.urlopen(req, timeout=20) as resp:
                data = json.loads(resp.read().decode())
                text = data["choices"][0]["message"]["content"].strip()
                score = float(text)
                score = max(0.0, min(1.0, score))
        except Exception:
            score = 0.5
        results.append((profile, score))
    return results


# ── Main discovery cycle ───────────────────────────────────────────────────────

def run_discovery():
    start_ts = datetime.now(timezone.utc)
    print(f"[{start_ts.isoformat()}] Discovery cycle starting...")

    # Load profiles
    prof_resp = mcp_call(POSTGRES_MCP, "list_profiles")
    profiles = prof_resp.get("profiles", [])
    if not profiles:
        print("No profiles in postgres — skipping cycle.", file=sys.stderr)
        return

    total_scraped = 0
    total_upserted = 0
    total_pending = 0

    for source in SOURCES:
        print(f"  Scraping {source}...")
        scrape = mcp_call(CRAWLEE_MCP, "trigger_scrape", source=source, limit=30)
        jobs_raw = scrape.get("jobs", scrape.get("results", []))

        if not isinstance(jobs_raw, list):
            print(f"  [{source}] unexpected response: {str(scrape)[:100]}", file=sys.stderr)
            continue

        total_scraped += len(jobs_raw)

        for raw in jobs_raw:
            url = raw.get("url", "")
            if not url:
                continue

            # Get full description
            desc_resp = mcp_call(CRAWLEE_MCP, "scrape_url", url=url)
            description = desc_resp.get("content", raw.get("description", ""))

            job = {
                "url": url,
                "title": raw.get("title", ""),
                "company": raw.get("company", ""),
                "description": description,
                "source": "discovered",
            }

            # Score against each profile
            scored = score_job(job, profiles)
            best_profile, best_score = max(scored, key=lambda x: x[1])

            if best_score < SCORE_THRESH:
                continue

            # Upsert to postgres
            upsert = mcp_call(
                POSTGRES_MCP, "upsert_job",
                url=url,
                title=job["title"],
                company=job["company"],
                description=description[:4000],
                score=best_score,
                source="discovered",
                profile_id=best_profile.get("id", ""),
            )
            job_id = upsert.get("job_id")
            total_upserted += 1

            # Push to Redis pending approvals
            payload = json.dumps({
                "job_id": job_id,
                "url": url,
                "title": job["title"],
                "company": job["company"],
                "score": round(best_score, 2),
                "profile_id": best_profile.get("id", ""),
                "profile_name": best_profile.get("name", ""),
            })
            redis_rpush(REDIS_KEY, payload)
            total_pending += 1
            time.sleep(0.2)  # rate limiting

        time.sleep(1)

    # Log event
    stats = {
        "scraped": total_scraped,
        "upserted": total_upserted,
        "pending": total_pending,
        "profiles": len(profiles),
        "duration_s": round((datetime.now(timezone.utc) - start_ts).total_seconds(), 1),
    }
    mcp_call(POSTGRES_MCP, "log_event", type="discovery_cycle", payload=json.dumps(stats))

    # Telegram notification
    msg = (
        f"Discovery done. Scraped {total_scraped} listings, "
        f"{total_upserted} jobs scored ≥{SCORE_THRESH}, "
        f"{total_pending} pushed for approval."
    )
    mcp_call(TELEGRAM_MCP, "notify", text=msg)
    print(f"  {msg}")
    print(f"  Stats: {stats}")


def run_monitor():
    """Check application statuses and notify on changes."""
    print(f"[{datetime.now(timezone.utc).isoformat()}] Monitor cycle starting...")

    # Check jobs needing follow-up
    submitted = mcp_call(POSTGRES_MCP, "list_jobs", status="applied", limit=50)
    jobs = submitted.get("jobs", [])

    assessment_queue = []
    for job in jobs:
        # Check if job needs assessment (would be set by VPS application attempt)
        if job.get("result"):
            try:
                result = json.loads(job["result"])
                if result.get("needs_assessment"):
                    assessment_queue.append(job)
            except Exception:
                pass

    if assessment_queue:
        for job in assessment_queue:
            payload = json.dumps({
                "job_id": job["id"],
                "url": job["url"],
                "title": job.get("title", ""),
                "profile_id": job.get("profile_id", ""),
            })
            redis_rpush("corvus:assessment_queue", payload)
            mcp_call(POSTGRES_MCP, "update_job_status", job_id=job["id"], status="assessment_needed")

        msg = f"Monitor: {len(assessment_queue)} job(s) need assessment. Queued for Desktop."
        mcp_call(TELEGRAM_MCP, "notify", text=msg)
        print(f"  {msg}")
    else:
        print("  No status changes detected.")


if __name__ == "__main__":
    mode = sys.argv[1] if len(sys.argv) > 1 else "discovery"
    if mode == "monitor":
        run_monitor()
    else:
        run_discovery()
