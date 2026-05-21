"""
corvus_discovery.py — Autonomous Track A job discovery for CareerBridge VPS.

Track A = gig / remote AI training / data annotation / micro-task roles.
Track B (professional jobs) = on-demand only when Mike pastes a URL. NOT discovered here.

Sources:
  - Serper API (Google search) for gig/AI-training listings across known platforms
  - Reddit r/WorkOnline, r/beermoney, r/HITsWorthTurkingFor via crawlee
  - Direct scrape of known gig platform career pages via Firecrawl

Run: python3 corvus_discovery.py [discovery|monitor]
"""
from __future__ import annotations

import json
import os
import re
import socket
import sys
import time
import urllib.request
import urllib.error
from datetime import datetime, timezone
from pathlib import Path

# ── Load .env ──────────────────────────────────────────────────────────────────

def _load_env(path: str = "/opt/corvus/.env") -> None:
    """Parse key=value pairs from .env and inject into os.environ."""
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

POSTGRES_MCP   = "http://localhost:8801"
CRAWLEE_MCP    = "http://localhost:8802"
TELEGRAM_MCP   = "http://localhost:8803"
REDIS_HOST     = "127.0.0.1"
REDIS_PORT     = 6379
REDIS_KEY      = "corvus:pending_approvals"
SCORE_THRESH   = 0.55          # lower bar for gig roles — less info in listings
OR_MODEL       = "openai/gpt-4o-mini"
OPENROUTER_KEY = os.environ.get("OPENROUTER_API_KEY", "")
SERPER_KEY     = os.environ.get("SERPER_API_KEY", "")

# Track A search queries — gig / AI training / data annotation only
TRACK_A_QUERIES = [
    "AI training data annotation remote work site:appen.com OR site:dataannotation.tech OR site:remotasks.com",
    "remote AI evaluator RLHF data labeling 2025 site:jobs.lever.co OR site:boards.greenhouse.io",
    "\"AI trainer\" OR \"data annotator\" OR \"content moderator\" remote freelance work from home",
    "scale AI remotasks outlier AI data annotation jobs hiring now",
    "TELUS international AI training clickworker toloka remote work 2025",
    "reddit.com/r/WorkOnline AI annotation training task",
]

# Direct gig-platform career pages to scrape via Firecrawl
TRACK_A_PAGES = [
    "https://www.appen.com/jobs/",
    "https://dataannotation.tech/hire",
    "https://www.outlier.ai/careers",
    "https://www.clickworker.com/clickworker/",
    "https://toloka.ai/jobs/",
    "https://surgehq.ai/careers",
    "https://www.telusinternational.com/solutions/ai-data/ai-training",
    "https://www.lionbridge.com/ai-training-data-services/",
]

# Reddit subreddits via crawlee (keyword filtered)
REDDIT_SOURCES = [
    ("reddit", "AI training annotation remote work"),
    ("reddit", "data labeling remote job work from home"),
    ("reddit", "beermoney AI annotator task"),
]


# ── HTTP helpers ───────────────────────────────────────────────────────────────

def _post(url: str, body: dict, headers: dict | None = None, timeout: int = 30) -> dict:
    data = json.dumps(body).encode()
    h = {"Content-Type": "application/json"}
    if headers:
        h.update(headers)
    req = urllib.request.Request(url, data=data, headers=h)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return json.loads(resp.read().decode())
    except Exception as e:
        return {"error": str(e)}


_mcp_seq = 0

def mcp_call(base: str, tool: str, **kwargs) -> dict:
    global _mcp_seq
    _mcp_seq += 1
    resp = _post(f"{base}/mcp", {
        "jsonrpc": "2.0", "id": _mcp_seq,
        "method": "tools/call",
        "params": {"name": tool, "arguments": kwargs},
    })
    if "error" in resp:
        return resp
    try:
        return json.loads(resp["result"]["content"][0]["text"])
    except Exception:
        return resp


# ── Redis ──────────────────────────────────────────────────────────────────────

def redis_rpush(key: str, value: str) -> None:
    try:
        with socket.create_connection((REDIS_HOST, REDIS_PORT), timeout=3) as sock:
            k, v = key.encode(), value.encode()
            cmd = f"*3\r\n$5\r\nRPUSH\r\n${len(k)}\r\n".encode() + k + f"\r\n${len(v)}\r\n".encode() + v + b"\r\n"
            sock.sendall(cmd)
            sock.recv(256)
    except Exception as e:
        print(f"[redis] RPUSH failed: {e}", file=sys.stderr)


# ── Serper (Google search) ─────────────────────────────────────────────────────

def serper_search(query: str, num: int = 10) -> list[dict]:
    """Return list of {title, link, snippet} from Google via Serper."""
    if not SERPER_KEY:
        return []
    body = {"q": query, "num": num, "gl": "gb", "hl": "en"}
    resp = _post(
        "https://google.serper.dev/search", body,
        headers={"X-API-KEY": SERPER_KEY}, timeout=15,
    )
    results = []
    for item in resp.get("organic", []):
        results.append({
            "title": item.get("title", ""),
            "url": item.get("link", ""),
            "snippet": item.get("snippet", ""),
            "company": _extract_company(item.get("link", ""), item.get("title", "")),
        })
    return results


def _extract_company(url: str, title: str) -> str:
    """Best-effort company name from URL or title."""
    known = {
        "appen.com": "Appen", "dataannotation.tech": "DataAnnotation",
        "remotasks.com": "Remotasks", "outlier.ai": "Outlier AI",
        "scale.com": "Scale AI", "surgehq.ai": "Surge HQ",
        "clickworker.com": "Clickworker", "toloka.ai": "Toloka",
        "telusinternational.com": "TELUS International",
        "lionbridge.com": "Lionbridge", "imerit.net": "iMerit",
        "prolific.com": "Prolific", "hive.com": "Hive",
        "sama.com": "Sama", "invisible.email": "Invisible Technologies",
        "reddit.com": "Reddit", "lever.co": "via Lever",
        "greenhouse.io": "via Greenhouse", "ashbyhq.com": "via Ashby",
    }
    for domain, name in known.items():
        if domain in url:
            return name
    # Fall back: extract from title "Role at Company — ..."
    m = re.search(r" at (.+?)[\s\|—–-]", title)
    if m:
        return m.group(1).strip()
    return "Unknown"


# ── Firecrawl direct page scrape ───────────────────────────────────────────────

def scrape_page_for_jobs(url: str) -> list[dict]:
    """Scrape a gig-platform careers page and extract job listings via LLM."""
    resp = mcp_call(CRAWLEE_MCP, "scrape_url", url=url)
    content = resp.get("content") or resp.get("text") or resp.get("markdown") or ""
    if not content or len(content) < 100:
        return []

    if not OPENROUTER_KEY:
        # Without LLM, return the page as one item so it still gets scored
        return [{"title": "Jobs at " + url.split("/")[2], "url": url,
                 "company": _extract_company(url, ""), "description": content[:1000]}]

    # Ask GPT-4o-mini to extract job listings from the scraped text
    prompt = (
        "Extract job listings from this careers page text. "
        "Return a JSON array of objects with keys: title, company, description (1-2 sentences), url.\n"
        "Only include REMOTE or WORK-FROM-HOME gig/freelance/contract roles related to:\n"
        "AI training, data annotation, content moderation, RLHF, data labeling, AI evaluation, micro-tasks.\n"
        "If no matching roles found, return [].\n\n"
        f"PAGE URL: {url}\n\nPAGE CONTENT:\n{content[:3000]}"
    )
    body = {
        "model": OR_MODEL,
        "messages": [{"role": "user", "content": prompt}],
        "max_tokens": 800,
        "response_format": {"type": "json_object"},
    }
    req = urllib.request.Request(
        "https://openrouter.ai/api/v1/chat/completions",
        data=json.dumps(body).encode(),
        headers={"Content-Type": "application/json", "Authorization": f"Bearer {OPENROUTER_KEY}"},
    )
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            raw = json.loads(r.read().decode())["choices"][0]["message"]["content"]
            parsed = json.loads(raw)
            items = parsed if isinstance(parsed, list) else parsed.get("jobs", parsed.get("listings", []))
            for item in items:
                if "url" not in item or not item["url"]:
                    item["url"] = url
                if "company" not in item or not item["company"]:
                    item["company"] = _extract_company(url, item.get("title", ""))
            return items
    except Exception:
        return []


# ── Scoring ────────────────────────────────────────────────────────────────────

def score_job(job: dict, profiles: list[dict]) -> list[tuple[dict, float]]:
    """Score a Track A gig job against each profile. Returns list of (profile, score)."""
    if not OPENROUTER_KEY:
        return [(p, 0.65) for p in profiles]

    results = []
    for profile in profiles:
        prompt = (
            "You are scoring a gig/remote work opportunity for a candidate.\n"
            "Reply with ONLY a decimal 0.0-1.0 (higher = better match).\n\n"
            "Consider: Is this a real remote gig job (AI training, annotation, evaluation)? "
            "Does it match the candidate's skills and background? Is it accessible for their location?\n\n"
            f"JOB TITLE: {job.get('title', 'Unknown')}\n"
            f"COMPANY/PLATFORM: {job.get('company', '')}\n"
            f"DESCRIPTION: {str(job.get('description', ''))[:600]}\n\n"
            f"CANDIDATE SKILLS: {profile.get('skills', '')}\n"
            f"CANDIDATE LOCATION: {profile.get('location', '')}\n"
            f"CANDIDATE BIO: {str(profile.get('bio', ''))[:300]}\n"
        )
        body = {
            "model": OR_MODEL,
            "messages": [{"role": "user", "content": prompt}],
            "max_tokens": 10,
        }
        req = urllib.request.Request(
            "https://openrouter.ai/api/v1/chat/completions",
            data=json.dumps(body).encode(),
            headers={"Content-Type": "application/json", "Authorization": f"Bearer {OPENROUTER_KEY}"},
        )
        try:
            with urllib.request.urlopen(req, timeout=20) as r:
                text = json.loads(r.read().decode())["choices"][0]["message"]["content"].strip()
                score = max(0.0, min(1.0, float(text)))
        except Exception:
            score = 0.5
        results.append((profile, score))
    return results


# ── Main discovery cycle ───────────────────────────────────────────────────────

def run_discovery():
    start_ts = datetime.now(timezone.utc)
    print(f"[{start_ts.isoformat()}] Discovery cycle starting (Track A — gig/AI training)...")

    # Load profiles
    prof_resp = mcp_call(POSTGRES_MCP, "list_profiles")
    profiles = prof_resp.get("profiles", [])
    if not profiles:
        print("No profiles in postgres — skipping cycle.", file=sys.stderr)
        return

    seen_urls: set[str] = set()
    all_jobs: list[dict] = []

    # ── 1. Serper search ──────────────────────────────────────────────────────
    if SERPER_KEY:
        print(f"  Searching via Serper ({len(TRACK_A_QUERIES)} queries)...")
        for query in TRACK_A_QUERIES:
            results = serper_search(query, num=10)
            for r in results:
                if r["url"] and r["url"] not in seen_urls:
                    seen_urls.add(r["url"])
                    all_jobs.append({
                        "url": r["url"],
                        "title": r["title"],
                        "company": r["company"],
                        "description": r["snippet"],
                        "source": "serper",
                    })
            time.sleep(0.5)
        print(f"  Serper: {len(all_jobs)} unique listings found")
    else:
        print("  [Serper] no key — skipping search", file=sys.stderr)

    # ── 2. Reddit via crawlee (keyword-filtered for gig/AI work) ─────────────
    print("  Scraping Reddit (gig AI work subreddits)...")
    for source, keywords in REDDIT_SOURCES:
        resp = mcp_call(CRAWLEE_MCP, "trigger_scrape", source=source, keywords=keywords, limit=20)
        items = resp.get("data", [])
        for raw in items:
            url = raw.get("website_url") or raw.get("url", "")
            if not url or url in seen_urls:
                continue
            seen_urls.add(url)
            company = raw.get("company_name") or _extract_company(url, raw.get("title", ""))
            title = raw.get("job_title") or raw.get("title") or "Work opportunity"
            all_jobs.append({
                "url": url,
                "title": title,
                "company": company,
                "description": raw.get("description", "")[:800],
                "source": "reddit",
            })
        time.sleep(0.5)
    print(f"  Reddit: {sum(1 for j in all_jobs if j['source'] == 'reddit')} items")

    # ── 3. Direct gig-platform page scrapes via Firecrawl ────────────────────
    print(f"  Scraping {len(TRACK_A_PAGES)} gig platform pages via Firecrawl...")
    for page_url in TRACK_A_PAGES:
        jobs_from_page = scrape_page_for_jobs(page_url)
        for j in jobs_from_page:
            if j.get("url") and j["url"] not in seen_urls:
                seen_urls.add(j["url"])
                j["source"] = "firecrawl"
                all_jobs.append(j)
        time.sleep(1)
    print(f"  Total candidates after all sources: {len(all_jobs)}")

    # ── 4. Score + upsert ────────────────────────────────────────────────────
    total_upserted = 0
    total_pending  = 0
    print(f"  Scoring {len(all_jobs)} listings against {len(profiles)} profile(s)...")

    for job in all_jobs:
        scored = score_job(job, profiles)
        best_profile, best_score = max(scored, key=lambda x: x[1])

        if best_score < SCORE_THRESH:
            continue

        upsert = mcp_call(
            POSTGRES_MCP, "upsert_job",
            url=job["url"],
            title=job.get("title", ""),
            company=job.get("company", ""),
            description=(job.get("description") or "")[:4000],
            score=best_score,
            source="discovered",
            profile_id=best_profile.get("id", ""),
        )
        job_id = upsert.get("job_id")
        if not job_id:
            continue
        total_upserted += 1

        payload = json.dumps({
            "job_id": job_id,
            "url": job["url"],
            "title": job.get("title", ""),
            "company": job.get("company", ""),
            "score": round(best_score, 2),
            "profile_id": best_profile.get("id", ""),
            "profile_name": best_profile.get("name", ""),
        })
        redis_rpush(REDIS_KEY, payload)
        total_pending += 1
        time.sleep(0.15)

    # ── 5. Log + notify ───────────────────────────────────────────────────────
    stats = {
        "scraped": len(all_jobs),
        "upserted": total_upserted,
        "pending": total_pending,
        "profiles": len(profiles),
        "duration_s": round((datetime.now(timezone.utc) - start_ts).total_seconds(), 1),
    }
    mcp_call(POSTGRES_MCP, "log_event", type="discovery_cycle", payload=json.dumps(stats))

    msg = (
        f"[Track A Discovery] {len(all_jobs)} listings scanned, "
        f"{total_upserted} scored ≥{SCORE_THRESH}, "
        f"{total_pending} queued for approval."
    )
    mcp_call(TELEGRAM_MCP, "notify", text=msg)
    print(f"  {msg}")
    print(f"  Stats: {stats}")


# ── Monitor cycle ──────────────────────────────────────────────────────────────

def run_monitor():
    print(f"[{datetime.now(timezone.utc).isoformat()}] Monitor cycle starting...")

    submitted = mcp_call(POSTGRES_MCP, "list_jobs", status="applied", limit=50)
    jobs = submitted.get("jobs", [])

    assessment_queue = []
    for job in jobs:
        if job.get("result"):
            try:
                result = json.loads(job["result"])
                if result.get("needs_assessment"):
                    assessment_queue.append(job)
            except Exception:
                pass

    if assessment_queue:
        for job in assessment_queue:
            redis_rpush("corvus:assessment_queue", json.dumps({
                "job_id": job["id"],
                "url": job["url"],
                "title": job.get("title", ""),
                "profile_id": job.get("profile_id", ""),
            }))
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
