"""
school_scraper.py — VPS school discovery for CareerBridge.

Pipeline:
  Phase 1 — College Scorecard API (US DoE): structured query for all open-admission
             institutions (community colleges + open-enrollment universities).
             community_college flag taken directly from API — no guessing.
  Phase 2 — Firecrawl (crawlee_mcp.scrape_url): visit each institution's page to
             read the 4 criteria the API cannot answer.
  Phase 3 — GPT-4o-mini (OpenRouter): extract no_id_verification, no_transcript,
             monthly_enrollment, instant_acceptance, monthly_refund from page text.
  Phase 4 — Serper supplementary: catch schools not in Scorecard (newer, niche,
             or unaccredited institutions). Deduplication prevents double-saves.

Run on VPS:
  python3 school_scraper.py                        # all sources, 100 schools/run
  python3 school_scraper.py --source scorecard      # Scorecard only
  python3 school_scraper.py --source serper         # Serper only
  python3 school_scraper.py --limit 500             # initial seeding run
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import sys
import time
import urllib.parse
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

CRAWLEE_MCP    = "http://localhost:8802"
SCORECARD_KEY  = os.environ.get("SCORECARD_API_KEY", "")
SERPER_KEY     = os.environ.get("SERPER_API_KEY", "")
OR_KEY         = os.environ.get("OPENROUTER_API_KEY", "")
OR_MODEL       = "openai/gpt-4o-mini"
DB_DSN         = os.environ.get("VPS_PG_DSN",
                     "postgresql://corvus:corvus-local-password@localhost:5432/careerbridge")

SCORECARD_BASE   = "https://api.data.gov/ed/collegescorecard/v1/schools"
SCORECARD_FIELDS = ",".join([
    "id",
    "school.name",
    "school.school_url",
    "school.city",
    "school.state",
    "school.online_only",
    "school.degrees_awarded.predominant",
    "school.ownership",
    "school.open_admissions_policy",
])


# ── HTTP helpers ───────────────────────────────────────────────────────────────

def _get(url: str, headers: dict | None = None, timeout: int = 20) -> dict | list:
    req = urllib.request.Request(url, headers={"User-Agent": "CareerBridge/1.0"})
    if headers:
        for k, v in headers.items():
            req.add_header(k, v)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return json.loads(r.read().decode())
    except Exception as e:
        print(f"[http] GET {url[:60]} error: {e}", file=sys.stderr)
        return {}


def _post(url: str, body: dict, headers: dict | None = None, timeout: int = 30) -> dict:
    data = json.dumps(body).encode()
    h = {"Content-Type": "application/json"}
    if headers:
        h.update(headers)
    req = urllib.request.Request(url, data=data, headers=h)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return json.loads(r.read().decode())
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


# ── DB ─────────────────────────────────────────────────────────────────────────

try:
    import psycopg2
    import psycopg2.extras
    HAS_DB = True
except ImportError:
    HAS_DB = False
    print("[school_scraper] psycopg2 not installed — dry-run mode", file=sys.stderr)


def get_db():
    return psycopg2.connect(DB_DSN, connect_timeout=10)


def ensure_table() -> None:
    if not HAS_DB:
        return
    sql = """
    CREATE TABLE IF NOT EXISTS schools (
        id                     SERIAL PRIMARY KEY,
        name                   TEXT NOT NULL,
        url                    TEXT,
        enrollment_url         TEXT,
        type                   TEXT,
        evidence               TEXT,
        no_id_verification     BOOLEAN DEFAULT FALSE,
        no_transcript_required BOOLEAN DEFAULT FALSE,
        monthly_enrollment     BOOLEAN DEFAULT FALSE,
        instant_acceptance     BOOLEAN DEFAULT FALSE,
        monthly_refund         BOOLEAN DEFAULT FALSE,
        community_college      BOOLEAN DEFAULT FALSE,
        filters                TEXT[],
        source_query           TEXT,
        url_hash               TEXT UNIQUE,
        created_at             TIMESTAMPTZ DEFAULT NOW(),
        updated_at             TIMESTAMPTZ DEFAULT NOW()
    );
    CREATE INDEX IF NOT EXISTS schools_filters_idx ON schools USING GIN(filters);
    """
    try:
        with get_db() as conn:
            with conn.cursor() as cur:
                cur.execute(sql)
            conn.commit()
        print("[db] schools table ready")
    except Exception as e:
        print(f"[db] unreachable ({e}) — dry-run mode", file=sys.stderr)


REFRESH_DAYS = 7   # re-scrape a school's page after this many days


def load_fresh_urls() -> set[str]:
    """Return URLs already scraped within REFRESH_DAYS — skip these in the current run."""
    if not HAS_DB:
        return set()
    try:
        from datetime import timedelta
        cutoff = datetime.now(timezone.utc) - timedelta(days=REFRESH_DAYS)
        with get_db() as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT url FROM schools WHERE updated_at > %s", (cutoff,))
                urls = {row[0] for row in cur.fetchall() if row[0]}
        print(f"[db] {len(urls)} schools fresh (scraped within {REFRESH_DAYS}d) — will skip")
        return urls
    except Exception as e:
        print(f"[db] load_fresh_urls: {e}", file=sys.stderr)
        return set()


def save_school(data: dict) -> bool:
    if not HAS_DB:
        print(f"[dry-run] {json.dumps({k: v for k, v in data.items() if k not in ('_score','_priority')}, default=str)[:200]}")
        return True
    url_hash = hashlib.md5((data.get("url") or data.get("name", "")).encode()).hexdigest()
    sql = """
    INSERT INTO schools (
        name, url, enrollment_url, type, evidence,
        no_id_verification, no_transcript_required, monthly_enrollment,
        instant_acceptance, monthly_refund, community_college,
        filters, source_query, url_hash, updated_at
    ) VALUES (
        %(name)s, %(url)s, %(enrollment_url)s, %(type)s, %(evidence)s,
        %(no_id_verification)s, %(no_transcript_required)s, %(monthly_enrollment)s,
        %(instant_acceptance)s, %(monthly_refund)s, %(community_college)s,
        %(filters)s, %(source_query)s, %(url_hash)s, NOW()
    )
    ON CONFLICT (url_hash) DO UPDATE SET
        evidence               = EXCLUDED.evidence,
        no_id_verification     = EXCLUDED.no_id_verification,
        no_transcript_required = EXCLUDED.no_transcript_required,
        monthly_enrollment     = EXCLUDED.monthly_enrollment,
        instant_acceptance     = EXCLUDED.instant_acceptance,
        monthly_refund         = EXCLUDED.monthly_refund,
        community_college      = EXCLUDED.community_college,
        filters                = EXCLUDED.filters,
        updated_at             = NOW()
    RETURNING id;
    """
    try:
        with get_db() as conn:
            with conn.cursor() as cur:
                cur.execute(sql, {**data, "url_hash": url_hash})
                row = cur.fetchone()
            conn.commit()
        return bool(row)
    except Exception as e:
        print(f"[db] save failed ({e})", file=sys.stderr)
        return False


# ── College Scorecard API ──────────────────────────────────────────────────────

def _scorecard_page(page: int, per_page: int = 100) -> dict:
    params = urllib.parse.urlencode({
        "api_key":                      SCORECARD_KEY,
        "school.open_admissions_policy": 1,
        "fields":                        SCORECARD_FIELDS,
        "per_page":                      per_page,
        "page":                          page,
    })
    return _get(f"{SCORECARD_BASE}?{params}")


def scorecard_candidates(fetch_limit: int = 2000) -> list[dict]:
    """
    Pull all open-admission US institutions from College Scorecard.
    Covers community colleges AND open-enrollment universities.
    Sorted by processing priority: online-only first, then CCs, then others.
    """
    if not SCORECARD_KEY:
        print("[scorecard] no SCORECARD_API_KEY in .env — skipping Scorecard phase", file=sys.stderr)
        return []

    all_schools: list[dict] = []
    page = 0
    per_page = 100

    while len(all_schools) < fetch_limit:
        data = _scorecard_page(page, per_page)
        results = data.get("results", [])
        if not results:
            break

        for r in results:
            name    = (r.get("school.name") or "").strip()
            raw_url = (r.get("school.school_url") or "").strip()
            if not name or not raw_url:
                continue
            if not raw_url.startswith("http"):
                raw_url = "https://" + raw_url

            predominant = r.get("school.degrees_awarded.predominant")  # 2 = associate's/CC
            online_only = int(r.get("school.online_only") or 0)
            ownership   = int(r.get("school.ownership") or 0)          # 3 = for-profit

            # Higher priority = processed first in each daily run
            priority = 0
            if online_only == 1:  priority += 3   # fully online → most likely to meet flexible criteria
            if predominant == 2:  priority += 2   # community college
            if ownership == 3:    priority += 1   # for-profit → often monthly/instant/refund

            all_schools.append({
                "name":                 name,
                "url":                  raw_url,
                "city":                 r.get("school.city", ""),
                "state":                r.get("school.state", ""),
                "is_community_college": predominant == 2,
                "online_only":          bool(online_only),
                "_priority":            priority,
            })

        meta    = data.get("metadata", {})
        total   = meta.get("total", 0)
        fetched = (page + 1) * per_page
        print(f"[scorecard] page {page}: +{len(results)} | {min(fetched, total)}/{total} total")

        if fetched >= total:
            break
        page += 1
        time.sleep(0.3)

    all_schools.sort(key=lambda s: s["_priority"], reverse=True)
    print(f"[scorecard] {len(all_schools)} open-admission institutions fetched and prioritized")
    return all_schools


# ── Page fetch via Firecrawl (crawlee_mcp) ────────────────────────────────────

def fetch_page(url: str) -> str:
    resp = mcp_call(CRAWLEE_MCP, "scrape_url", url=url)
    content = resp.get("content") or resp.get("text") or resp.get("markdown") or ""
    if not content:
        print(f"[firecrawl] empty for {url[:60]}", file=sys.stderr)
    return content[:6000]


# ── GPT-4o-mini criteria analysis ─────────────────────────────────────────────

CRITERIA_PROMPT = """\
You are an admissions analyst. Given the text from a school's website,
determine which of these criteria the school meets:

1. no_id_verification — can students enroll without submitting government-issued ID?
2. no_transcript — no high-school or prior transcripts required for enrollment?
3. monthly_enrollment — does the school accept new students every month or rolling basis?
4. instant_acceptance — are applications accepted/approved immediately or near-instantly?
5. monthly_refund — does the school issue tuition refunds on a monthly schedule?

Note: do NOT assess community_college — that is determined separately.

Output ONLY a JSON object:
{
  "no_id_verification": false,
  "no_transcript": true,
  "monthly_enrollment": true,
  "instant_acceptance": false,
  "monthly_refund": false,
  "evidence": "One sentence summarizing the key evidence from the page."
}

School website text:
---
{TEXT}
---"""


def analyze_school(name: str, page_text: str) -> dict:
    """Extract 5 enrollment criteria using GPT-4o-mini. Falls back to heuristics."""
    if not OR_KEY or not page_text:
        return _heuristic_analyze(name, page_text)
    prompt = CRITERIA_PROMPT.replace("{TEXT}", page_text[:4000])
    body = {
        "model": OR_MODEL,
        "messages": [{"role": "user", "content": prompt}],
        "max_tokens": 400,
    }
    req = urllib.request.Request(
        "https://openrouter.ai/api/v1/chat/completions",
        data=json.dumps(body).encode(),
        headers={"Content-Type": "application/json", "Authorization": f"Bearer {OR_KEY}"},
    )
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            raw = json.loads(r.read().decode())["choices"][0]["message"]["content"].strip()
        raw = re.sub(r"^```(?:json)?\s*", "", raw)
        raw = re.sub(r"\s*```$", "", raw).strip()
        return json.loads(raw)
    except Exception as e:
        print(f"[gpt-analyze] {name[:40]}: {e}", file=sys.stderr)
        return _heuristic_analyze(name, page_text)


# ── Heuristic fallback ────────────────────────────────────────────────────────

_ID_DENY   = re.compile(r"government.?issued|photo id|driver.?licen|passport|id verification", re.I)
_MONTHLY   = re.compile(r"monthly\s+(?:enrollment|intake|start)|rolling\s+admission|start\s+every\s+month|multiple\s+start\s+dates", re.I)
_INSTANT   = re.compile(r"instant(?:ly)?\s+accept|immediate\s+(?:accept|enroll|decision)|admitted\s+immediately|apply\s+and\s+start\s+today", re.I)
_NO_TRANS  = re.compile(r"no\s+transcript|without\s+transcript|transcript\s+not\s+required", re.I)
_REQ_TRANS = re.compile(r"official\s+transcript|require\s+transcript", re.I)
_REFUND    = re.compile(r"monthly\s+refund|refund\s+schedule|pro-?rated\s+refund", re.I)
_COMMUNITY = re.compile(r"community\s+college|two[- ]year\s+college|2[- ]year\s+college", re.I)


def _heuristic_analyze(name: str, text: str) -> dict:
    d = {
        "community_college":  bool(_COMMUNITY.search(name) or _COMMUNITY.search(text)),
        "no_id_verification": not bool(_ID_DENY.search(text)),
        "no_transcript":      bool(_NO_TRANS.search(text)) or not bool(_REQ_TRANS.search(text)),
        "monthly_enrollment": bool(_MONTHLY.search(text)),
        "instant_acceptance": bool(_INSTANT.search(text)),
        "monthly_refund":     bool(_REFUND.search(text)),
        "evidence":           "",
    }
    bits = []
    if d["monthly_enrollment"]: bits.append("rolling/monthly enrollment")
    if d["instant_acceptance"]: bits.append("instant acceptance")
    if d["no_id_verification"]: bits.append("no ID verification")
    if d["no_transcript"]:      bits.append("no transcript needed")
    if d["monthly_refund"]:     bits.append("monthly refund policy")
    d["evidence"] = "; ".join(bits) if bits else "Enrollment terms not clearly stated"
    return d


# ── Build school record from analysis ─────────────────────────────────────────

_FLAG_MAP = {
    "community_college":  "community_college",
    "no_id_verification": "no_id_verification",
    "no_transcript":      "no_transcript_required",
    "monthly_enrollment": "monthly_enrollment",
    "instant_acceptance": "instant_acceptance",
    "monthly_refund":     "monthly_refund",
}

def _build_record(name: str, url: str, analysis: dict,
                  is_cc: bool, source_query: str) -> dict:
    analysis["community_college"] = is_cc  # API value overrides page analysis
    active = [col for k, col in _FLAG_MAP.items() if analysis.get(k)]
    return {
        "name":                   name,
        "url":                    url,
        "enrollment_url":         url,
        "type":                   "Community College" if is_cc else "University/College",
        "evidence":               analysis.get("evidence", ""),
        "no_id_verification":     bool(analysis.get("no_id_verification")),
        "no_transcript_required": bool(analysis.get("no_transcript")),
        "monthly_enrollment":     bool(analysis.get("monthly_enrollment")),
        "instant_acceptance":     bool(analysis.get("instant_acceptance")),
        "monthly_refund":         bool(analysis.get("monthly_refund")),
        "community_college":      bool(is_cc),
        "filters":                active,
        "source_query":           source_query,
        "_score":                 len(active),
    }


# ── Phase 1: Scorecard pipeline ───────────────────────────────────────────────

def run_scorecard_pipeline(candidates: list[dict], limit: int,
                           seen_urls: set[str],
                           fresh_urls: set[str]) -> list[dict]:
    """
    Firecrawl + analyze Scorecard candidates, up to `limit` per run.
    Skips URLs already scraped within REFRESH_DAYS (fresh_urls).
    New schools are processed first; stale schools fill remaining capacity.
    """
    # Split into new (never in DB) and stale (in DB but past refresh window)
    new_candidates   = [c for c in candidates if c["url"] not in seen_urls and c["url"] not in fresh_urls]
    stale_candidates = [c for c in candidates if c["url"] not in seen_urls and c["url"] in fresh_urls]

    # Process new first, then stale to fill remaining slots
    to_process = (new_candidates + stale_candidates)[:limit]

    if not to_process:
        print("[scorecard] nothing to process — all candidates fresh or already seen this run")
        return []

    n_new   = sum(1 for c in to_process if c["url"] not in fresh_urls)
    n_stale = len(to_process) - n_new
    print(f"[scorecard] processing {len(to_process)} ({n_new} new, {n_stale} refreshing) with Firecrawl + GPT-4o-mini")
    results = []

    for i, inst in enumerate(to_process):
        name = inst["name"]
        url  = inst["url"]
        seen_urls.add(url)
        tag  = "CC" if inst["is_community_college"] else ("Online" if inst["online_only"] else "Uni")
        status = "new" if url not in fresh_urls else "refresh"
        print(f"  [{i+1}/{len(to_process)}] [{tag}] [{status}] {name[:55]}")

        page_text = fetch_page(url)
        time.sleep(0.5)

        analysis = analyze_school(name, page_text)
        record   = _build_record(name, url, analysis,
                                 is_cc=inst["is_community_college"],
                                 source_query="scorecard_api")
        results.append(record)
        saved = save_school(record)
        print(f"     score={record['_score']}/6  filters={record['filters'] or ['none']}  saved={saved}")

    return results


# ── Phase 2: Serper supplementary ─────────────────────────────────────────────

_SKIP_DOMAINS = {
    "indeed.com", "glassdoor.com", "linkedin.com", "reddit.com", "quora.com",
    "niche.com", "collegeconfidential.com", "cappex.com", "unigo.com",
    "studyportals.com", "youtube.com", "facebook.com", "wikipedia.org",
}

SEARCH_QUERIES: dict[str, list[str]] = {
    "best_match": [
        "online community college monthly enrollment no ID verification no transcript instant acceptance",
        "fully online college rolling admission no government ID no transcripts monthly start date",
        "open enrollment online community college monthly refund policy instant acceptance",
        "online university enroll without ID monthly intake no transcript required same-day acceptance",
    ],
    "community_college": [
        "US community college fully online open enrollment no ID verification",
        "online community college monthly enrollment",
        "community college accept students without ID verification online",
        "open admission community college rolling enrollment online",
    ],
    "no_id_verification": [
        "online university enroll without government ID verification",
        "online college no identity verification required enrollment",
        "distance learning university open enrollment no ID check",
    ],
    "no_transcript": [
        "online university no transcript required for enrollment",
        "college enroll without high school transcript online",
        "open admission university no prior academic records needed",
    ],
    "monthly_enrollment": [
        "university monthly rolling enrollment start any month online",
        "online college multiple start dates monthly",
        "distance university monthly intake open enrollment",
    ],
    "instant_acceptance": [
        "online college instant admission acceptance same day",
        "university apply and start immediately no waiting period online",
        "instant enrollment online degree program no application wait",
    ],
    "monthly_refund": [
        "university monthly tuition refund schedule policy",
        "online college pro-rated monthly refund enrollment",
    ],
}


def _serper_search(query: str, n: int = 8) -> list[dict]:
    if not SERPER_KEY:
        return []
    resp = _post(
        "https://google.serper.dev/search",
        {"q": query, "num": n, "gl": "us", "hl": "en"},
        headers={"X-API-KEY": SERPER_KEY, "Content-Type": "application/json"},
        timeout=15,
    )
    if "error" in resp:
        print(f"[serper] {resp['error']}", file=sys.stderr)
        return []
    results = []
    for item in resp.get("organic", []):
        url = item.get("link", "")
        if not url or any(d in url for d in _SKIP_DOMAINS):
            continue
        results.append({"title": item.get("title", ""), "url": url, "snippet": item.get("snippet", "")})
    return results


def run_serper_pipeline(filter_name: str, custom_query: str,
                        seen_urls: set[str]) -> list[dict]:
    queries = ([custom_query] if custom_query else []) + SEARCH_QUERIES.get(filter_name, [])
    results = []

    for query in queries[:4]:
        print(f"  [serper] {query[:70]}")
        hits = _serper_search(query, n=8)
        time.sleep(1)

        for hit in hits:
            url = hit.get("url", "")
            if not url or url in seen_urls:
                continue
            seen_urls.add(url)

            name = (hit.get("title") or url)[:100]
            print(f"    -> {name[:65]}")

            page_text = fetch_page(url)
            time.sleep(0.5)

            analysis = analyze_school(name, page_text)
            # For Serper results, infer community_college from heuristics (no API data)
            is_cc    = bool(_heuristic_analyze(name, page_text).get("community_college"))
            record   = _build_record(name, url, analysis, is_cc=is_cc, source_query=query)
            results.append(record)
            saved = save_school(record)
            print(f"     score={record['_score']}/6  filters={record['filters'] or ['none']}  saved={saved}")

    return results


# ── Report ─────────────────────────────────────────────────────────────────────

def _print_report(all_results: list[dict]) -> None:
    all_results.sort(key=lambda s: s.get("_score", 0), reverse=True)

    print(f"\n{'='*70}")
    print("SCHOOL SCRAPER REPORT")
    print(f"Generated: {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}")
    print(f"{'='*70}")
    print(f"Total processed this run: {len(all_results)}")

    tiers: dict[int, list] = {}
    for s in all_results:
        tiers.setdefault(s.get("_score", 0), []).append(s)

    print("\n--- Results by criteria score (6 = meets ALL) ---\n")
    for score in sorted(tiers.keys(), reverse=True):
        schools = tiers[score]
        if not schools:
            continue
        marker = "[BEST]" if score == 6 else ("[GOOD]" if score >= 4 else "     ")
        print(f"  {marker} Score {score}/6 -- {len(schools)} school(s)")
        for s in schools[:5]:
            print(f"     * {s['name'][:65]}")
            print(f"       {s['url']}")
            if s.get("evidence"):
                print(f"       Evidence: {s['evidence'][:100]}")
            if s.get("filters"):
                print(f"       Criteria: {', '.join(s['filters'])}")

    print(f"\n{'='*70}")
    scorecard_n = sum(1 for s in all_results if s.get("source_query") == "scorecard_api")
    serper_n    = len(all_results) - scorecard_n
    print(f"Sources: {scorecard_n} from College Scorecard API, {serper_n} from Serper")
    print("All results saved to DB (schools table).")


# ── CLI ────────────────────────────────────────────────────────────────────────

def main() -> None:
    parser = argparse.ArgumentParser(description="School Enrollment Scraper (VPS)")
    parser.add_argument(
        "--source", choices=["scorecard", "serper", "all"], default="all",
        help="Data source: scorecard API, serper search, or both (default: all)"
    )
    parser.add_argument(
        "--limit", type=int, default=500,
        help="Max schools to Firecrawl per run from Scorecard (default: 500)."
    )
    parser.add_argument(
        "--filter", choices=list(SEARCH_QUERIES.keys()) + ["all"], default="all",
        help="Serper filter category (default: all)"
    )
    parser.add_argument("--custom", default="", help="Extra Serper search query")
    args = parser.parse_args()

    ensure_table()

    seen_urls:   set[str]  = set()
    all_results: list[dict] = []

    # Load schools already scraped recently — skip these to avoid redundant work
    fresh_urls = load_fresh_urls()

    # ── Phase 1: College Scorecard API ────────────────────────────────────────
    if args.source in ("scorecard", "all"):
        print(f"\n{'='*60}\nPhase 1 — College Scorecard API\n{'='*60}")
        candidates = scorecard_candidates(fetch_limit=5000)
        results    = run_scorecard_pipeline(candidates, limit=args.limit,
                                            seen_urls=seen_urls, fresh_urls=fresh_urls)
        all_results.extend(results)
        time.sleep(2)

    # ── Phase 2: Serper supplementary ─────────────────────────────────────────
    if args.source in ("serper", "all") and SERPER_KEY:
        print(f"\n{'='*60}\nPhase 2 — Serper supplementary\n{'='*60}")
        filters_to_run = (
            ["best_match"] + [k for k in SEARCH_QUERIES if k != "best_match"]
            if args.filter == "all" else [args.filter]
        )
        for filt in filters_to_run:
            print(f"\n-- {filt} --")
            results = run_serper_pipeline(filt, args.custom, seen_urls=seen_urls)
            all_results.extend(results)
            time.sleep(2)
    elif args.source in ("serper", "all") and not SERPER_KEY:
        print("[serper] no SERPER_API_KEY — skipping supplementary phase")

    _print_report(all_results)


if __name__ == "__main__":
    main()
