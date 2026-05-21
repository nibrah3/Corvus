"""
corvus_discovery.py — Autonomous Track A job discovery for CareerBridge VPS.

Track A = gig / remote AI training / data annotation / micro-task roles.
Track B (professional jobs) = on-demand only when Mike pastes a URL. NOT here.

No scoring. Every discovered Track A job is pushed to pending_approvals.
CV tailoring handles the match — a relevance score is not needed or wanted.

Sources:
  - Serper API (Google search) across known Track A platforms
  - Reddit gig/AI work subreddits via crawlee
  - Direct Firecrawl scrape of known gig platform career pages

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
from datetime import datetime, timezone


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

POSTGRES_MCP   = "http://localhost:8801"
CRAWLEE_MCP    = "http://localhost:8802"
TELEGRAM_MCP   = "http://localhost:8803"
REDIS_HOST     = "127.0.0.1"
REDIS_PORT     = 6379
REDIS_KEY      = "corvus:pending_approvals"
OR_MODEL       = "openai/gpt-4o-mini"
OPENROUTER_KEY = os.environ.get("OPENROUTER_API_KEY", "")
SERPER_KEY     = os.environ.get("SERPER_API_KEY", "")

# Track A search queries — gig / AI training / data annotation ONLY
TRACK_A_QUERIES = [
    "AI training data annotation remote work site:appen.com OR site:dataannotation.tech OR site:remotasks.com",
    "remote AI evaluator RLHF data labeling jobs 2025",
    '"AI trainer" OR "data annotator" OR "content moderator" remote work from home freelance',
    "scale AI remotasks outlier AI data annotation hiring now",
    "TELUS international AI training clickworker toloka remote 2025",
    "site:reddit.com/r/WorkOnline AI annotation training task",
    "site:reddit.com/r/beermoney AI evaluator data labeling paid",
    "prolific.com tasks AI annotation research participant",
    "hive.ai sama.com iMerit AI training jobs remote",
    "lionbridge AI training data services freelance work",
]

# Known gig platform career/join pages — scraped directly via Firecrawl
TRACK_A_PAGES = [
    "https://www.appen.com/jobs/",
    "https://dataannotation.tech/hire",
    "https://www.outlier.ai/careers",
    "https://remotasks.com/en/jobs",
    "https://www.clickworker.com/clickworker/",
    "https://toloka.ai/jobs/",
    "https://surgehq.ai/careers",
    "https://www.telusinternational.com/solutions/ai-data/ai-training",
    "https://www.lionbridge.com/ai-training-data-services/",
    "https://sama.com/careers/",
    "https://hive.com/about/jobs",
]

# Reddit gig subreddits via crawlee
REDDIT_SOURCES = [
    ("reddit", "AI training annotation remote work"),
    ("reddit", "data labeling remote job work from home"),
    ("reddit", "beermoney AI annotator task evaluator"),
]

# Greenhouse ATS board slugs for known Track A companies
# Add slug to include; function handles 404/empty gracefully
GREENHOUSE_BOARDS = [
    "prolific",      # 128 AI Trainer roles — confirmed Track A
    "remotasks",     # AI Training for Igbo Writers, Video Description etc.
    # scaleai removed — board only has professional engineering roles (Track B)
    # toloka removed — 0 Track A matches after keyword tightening
]

# Keywords that mark a job as Track A (case-insensitive, any match → include)
# Deliberately narrow: "freelance"/"gig" are too broad and match professional roles
TRACK_A_KEYWORDS = [
    "ai trainer", "ai training", "data annotation", "data annotator",
    "data labeling", "data labelling", "content moderator", "content moderation",
    "rlhf", "ai evaluator", "ai feedback", "ai reviewer",
    "annotation specialist", "labeling specialist", "labelling specialist",
    "image annotation", "video annotation", "text annotation",
    "speech annotation", "audio annotation",
    "machine learning trainer", "model trainer", "response quality",
    "human feedback", "search quality", "quality rater",
    "micro task", "micro-task", "crowdsource", "crowd work",
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
            cmd = (
                f"*3\r\n$5\r\nRPUSH\r\n${len(k)}\r\n".encode() + k
                + f"\r\n${len(v)}\r\n".encode() + v + b"\r\n"
            )
            sock.sendall(cmd)
            sock.recv(256)
    except Exception as e:
        print(f"[redis] RPUSH failed: {e}", file=sys.stderr)


# ── Serper (Google search) ─────────────────────────────────────────────────────

_SERPER_NOISE_DOMAINS = {
    "youtube.com", "facebook.com", "instagram.com", "twitter.com", "x.com",
    "wikipedia.org", "reddit.com/r/wiki", "amazon.com", "tiktok.com",
    "pinterest.com", "glassdoor.com/blog", "quora.com",
}

def _is_noise_url(url: str) -> bool:
    return any(d in url for d in _SERPER_NOISE_DOMAINS)


def serper_search(query: str, num: int = 10) -> list[dict]:
    if not SERPER_KEY:
        return []
    resp = _post(
        "https://google.serper.dev/search",
        {"q": query, "num": num, "gl": "gb", "hl": "en"},
        headers={"X-API-KEY": SERPER_KEY},
        timeout=15,
    )
    results = []
    for item in resp.get("organic", []):
        url = item.get("link", "")
        if not url or _is_noise_url(url):
            continue
        results.append({
            "title": item.get("title", ""),
            "url": url,
            "company": _company_from(url, item.get("title", "")),
            "description": item.get("snippet", ""),
            "source": "serper",
        })
    return results


def _company_from(url: str, title: str) -> str:
    known = {
        "appen.com": "Appen",
        "dataannotation.tech": "DataAnnotation",
        "remotasks.com": "Remotasks",
        "outlier.ai": "Outlier AI",
        "scale.com": "Scale AI",
        "surgehq.ai": "Surge HQ",
        "clickworker.com": "Clickworker",
        "toloka.ai": "Toloka",
        "telusinternational.com": "TELUS International",
        "lionbridge.com": "Lionbridge",
        "imerit.net": "iMerit",
        "prolific.com": "Prolific",
        "hive.com": "Hive",
        "sama.com": "Sama",
        "invisible.email": "Invisible Technologies",
        "reddit.com": "Reddit",
        "lever.co": "via Lever",
        "greenhouse.io": "via Greenhouse",
        "ashbyhq.com": "via Ashby",
        "prolific.greenhouse.io": "Prolific",
        "appen.greenhouse.io": "Appen",
        "scaleai.greenhouse.io": "Scale AI",
        "outlier.greenhouse.io": "Outlier AI",
        "surgehq.greenhouse.io": "Surge HQ",
        "sama.greenhouse.io": "Sama",
        "hive.greenhouse.io": "Hive",
        "telusinternational.greenhouse.io": "TELUS International",
        "lionbridge.greenhouse.io": "Lionbridge",
        "clickworker.greenhouse.io": "Clickworker",
    }
    for domain, name in known.items():
        if domain in url:
            return name
    m = re.search(r" at ([^|—–\-]+)", title)
    if m:
        return m.group(1).strip()
    try:
        return url.split("/")[2].replace("www.", "")
    except Exception:
        return "Unknown"


# ── Greenhouse ATS direct API ─────────────────────────────────────────────────

def _is_track_a(text: str) -> bool:
    low = text.lower()
    return any(kw in low for kw in TRACK_A_KEYWORDS)


def scrape_greenhouse(slug: str) -> list[dict]:
    """Fetch individual job postings from a Greenhouse ATS board."""
    url = f"https://boards-api.greenhouse.io/v1/boards/{slug}/jobs?content=true"
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    try:
        with urllib.request.urlopen(req, timeout=20) as resp:
            data = json.loads(resp.read().decode())
    except Exception as e:
        print(f"  [greenhouse/{slug}] error: {e}", file=sys.stderr)
        return []

    jobs = data.get("jobs", [])
    results = []
    for job in jobs:
        title = job.get("title", "")
        dept = " ".join(d.get("name", "") for d in job.get("departments", []))
        location = " ".join(o.get("name", "") for o in job.get("offices", []))
        apply_url = job.get("absolute_url", "")
        content = job.get("content", "")

        combined = f"{title} {dept} {content[:500]}"
        if not _is_track_a(combined):
            continue

        results.append({
            "title": title,
            "url": apply_url or f"https://boards.greenhouse.io/{slug}",
            "company": _company_from(f"{slug}.greenhouse.io", title),
            "description": f"{location} | {content[:600]}".strip(" |"),
            "source": "greenhouse",
        })
    return results


# ── Firecrawl page scrape + LLM extraction ────────────────────────────────────

def scrape_page_for_jobs(url: str) -> list[dict]:
    """Scrape a gig-platform page and extract job listings via gpt-4o-mini."""
    resp = mcp_call(CRAWLEE_MCP, "scrape_url", url=url)
    content = resp.get("content") or resp.get("text") or resp.get("markdown") or ""
    if not content or len(content) < 100:
        return []

    if not OPENROUTER_KEY:
        return [{
            "title": "Jobs at " + url.split("/")[2],
            "url": url,
            "company": _company_from(url, ""),
            "description": content[:800],
            "source": "firecrawl",
        }]

    prompt = (
        "Extract job/work listings from this page. "
        "Return a JSON object with key 'jobs' — an array where each item has: "
        "title (str), company (str), description (1-2 sentences), url (str).\n"
        "Only include REMOTE or work-from-home gig/freelance/contract roles related to: "
        "AI training, data annotation, content moderation, RLHF, data labeling, "
        "AI evaluation, micro-tasks, crowd work, AI feedback.\n"
        "If nothing matches, return {\"jobs\": []}.\n\n"
        f"PAGE: {url}\n\nCONTENT:\n{content[:3500]}"
    )
    body = {
        "model": OR_MODEL,
        "messages": [{"role": "user", "content": prompt}],
        "max_tokens": 1000,
    }
    req = urllib.request.Request(
        "https://openrouter.ai/api/v1/chat/completions",
        data=json.dumps(body).encode(),
        headers={"Content-Type": "application/json", "Authorization": f"Bearer {OPENROUTER_KEY}"},
    )
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            raw = json.loads(r.read().decode())["choices"][0]["message"]["content"].strip()
            # Strip markdown fences if present
            raw = re.sub(r"^```(?:json)?\s*", "", raw)
            raw = re.sub(r"\s*```$", "", raw)
            parsed = json.loads(raw)
            items = parsed.get("jobs", parsed) if isinstance(parsed, dict) else parsed
            if not isinstance(items, list):
                return []
            for item in items:
                if not item.get("url"):
                    item["url"] = url
                if not item.get("company"):
                    item["company"] = _company_from(url, item.get("title", ""))
                item["source"] = "firecrawl"
            return items
    except Exception as e:
        print(f"  [firecrawl extract error {url[:40]}]: {e}", file=sys.stderr)
        return []


# ── Discovery cycle ────────────────────────────────────────────────────────────

def run_discovery():
    start_ts = datetime.now(timezone.utc)
    print(f"[{start_ts.isoformat()}] Track A discovery starting...")

    # Need at least one profile to tag jobs against
    prof_resp = mcp_call(POSTGRES_MCP, "list_profiles")
    profiles = prof_resp.get("profiles", [])
    if not profiles:
        print("No profiles in postgres — skipping cycle.", file=sys.stderr)
        return

    # Use first profile as default tag (no scoring — just ownership)
    default_profile = profiles[0]

    seen_urls: set[str] = set()
    all_jobs: list[dict] = []

    # 1. Serper search ──────────────────────────────────────────────────────────
    if SERPER_KEY:
        print(f"  [Serper] Running {len(TRACK_A_QUERIES)} queries...")
        for query in TRACK_A_QUERIES:
            results = serper_search(query, num=10)
            added = 0
            for r in results:
                if r["url"] and r["url"] not in seen_urls:
                    seen_urls.add(r["url"])
                    all_jobs.append(r)
                    added += 1
            print(f"    +{added} | {query[:60]}")
            time.sleep(0.4)
        print(f"  [Serper] {sum(1 for j in all_jobs if j['source'] == 'serper')} unique listings")
    else:
        print("  [Serper] no key — skipping", file=sys.stderr)

    # 2. Reddit via crawlee ─────────────────────────────────────────────────────
    print(f"  [Reddit] {len(REDDIT_SOURCES)} keyword searches...")
    for source, keywords in REDDIT_SOURCES:
        resp = mcp_call(CRAWLEE_MCP, "trigger_scrape", source=source, keywords=keywords, limit=25)
        items = resp.get("data", [])
        added = 0
        for raw in items:
            url = raw.get("website_url") or raw.get("url", "")
            if not url or url in seen_urls:
                continue
            seen_urls.add(url)
            company = raw.get("company_name") or _company_from(url, raw.get("title", ""))
            title = raw.get("job_title") or raw.get("title") or "Work opportunity"
            all_jobs.append({
                "url": url, "title": title, "company": company,
                "description": (raw.get("description") or "")[:800],
                "source": "reddit",
            })
            added += 1
        print(f"    +{added} | {keywords[:50]}")
        time.sleep(0.5)

    # 3. Greenhouse ATS boards (real individual postings) ──────────────────────
    print(f"  [Greenhouse] Querying {len(GREENHOUSE_BOARDS)} ATS boards...")
    for slug in GREENHOUSE_BOARDS:
        jobs_from_gh = scrape_greenhouse(slug)
        added = 0
        for j in jobs_from_gh:
            if j.get("url") and j["url"] not in seen_urls:
                seen_urls.add(j["url"])
                all_jobs.append(j)
                added += 1
        print(f"    +{added} Track A | {slug}")
        time.sleep(0.5)
    gh_count = sum(1 for j in all_jobs if j.get("source") == "greenhouse")
    print(f"  [Greenhouse] {gh_count} total Track A individual postings")

    # 4. Direct gig-platform page scrapes ──────────────────────────────────────
    print(f"  [Firecrawl] Scraping {len(TRACK_A_PAGES)} gig platform pages...")
    for page_url in TRACK_A_PAGES:
        jobs_from_page = scrape_page_for_jobs(page_url)
        added = 0
        for j in jobs_from_page:
            if j.get("url") and j["url"] not in seen_urls:
                seen_urls.add(j["url"])
                all_jobs.append(j)
                added += 1
        print(f"    +{added} | {page_url}")
        time.sleep(1)

    print(f"  Total discovered: {len(all_jobs)}")

    # 5. Upsert ALL jobs — no scoring, no threshold ────────────────────────────
    print(f"  Upserting to postgres and pushing to approval queue...")
    total_upserted = 0
    total_skipped  = 0

    for job in all_jobs:
        upsert = mcp_call(
            POSTGRES_MCP, "upsert_job",
            url=job["url"],
            title=(job.get("title") or "")[:500],
            company=(job.get("company") or "")[:200],
            description=(job.get("description") or "")[:4000],
            score=0.0,          # score is irrelevant — CV tailoring handles fit
            source="discovered",
            profile_id=default_profile.get("id", ""),
        )
        job_id = upsert.get("job_id")
        if not job_id:
            total_skipped += 1
            continue

        redis_rpush(REDIS_KEY, json.dumps({
            "job_id": job_id,
            "url": job["url"],
            "title": job.get("title", ""),
            "company": job.get("company", ""),
            "source": job.get("source", "discovered"),
            "profile_id": default_profile.get("id", ""),
            "profile_name": default_profile.get("name", ""),
        }))
        total_upserted += 1
        time.sleep(0.1)

    # 6. Log + notify ──────────────────────────────────────────────────────────
    duration_s = round((datetime.now(timezone.utc) - start_ts).total_seconds(), 1)
    stats = {
        "scraped": len(all_jobs),
        "upserted": total_upserted,
        "skipped": total_skipped,
        "profiles": len(profiles),
        "duration_s": duration_s,
    }
    mcp_call(POSTGRES_MCP, "log_event", type="discovery_cycle", payload=json.dumps(stats))

    msg = (
        f"[Track A] {len(all_jobs)} listings found, "
        f"{total_upserted} queued for approval. "
        f"({duration_s}s)"
    )
    mcp_call(TELEGRAM_MCP, "notify", text=msg)
    print(f"\n  {msg}")
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
                "job_id": job["id"], "url": job["url"],
                "title": job.get("title", ""), "profile_id": job.get("profile_id", ""),
            }))
            mcp_call(POSTGRES_MCP, "update_job_status", job_id=job["id"], status="assessment_needed")
        msg = f"Monitor: {len(assessment_queue)} job(s) queued for Desktop assessment."
        mcp_call(TELEGRAM_MCP, "notify", text=msg)
        print(f"  {msg}")
    else:
        print("  No status changes.")


if __name__ == "__main__":
    mode = sys.argv[1] if len(sys.argv) > 1 else "discovery"
    if mode == "monitor":
        run_monitor()
    else:
        run_discovery()
