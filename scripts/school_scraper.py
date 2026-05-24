"""
School Enrollment Scraper — CareerBridge
=========================================
Finds fully-online institutions meeting one or more of:
  • community_college     — community college
  • no_id_verification   — enrolls without ID verification
  • no_transcript        — no transcript required
  • monthly_enrollment   — enrols every month (rolling admission)
  • instant_acceptance   — accepts applications immediately
  • monthly_refund       — pays refunds on monthly schedule

For each school: collects name, URL, enrollment URL, evidence text,
and which filters it passes.  Stores in PostgreSQL schools table.

Run:  py -3 school_scraper.py [--filter monthly_enrollment] [--custom "..."]
"""
import os, sys, re, json, time, logging, argparse, hashlib
from datetime import datetime
sys.path.insert(0, os.path.dirname(__file__))

for line in open(os.path.join(os.path.dirname(__file__), "..", ".env")).read().splitlines():
    if "=" in line and not line.startswith("#"):
        k, _, v = line.partition("=")
        os.environ[k.strip()] = v.strip()

import requests
from bs4 import BeautifulSoup

log = logging.getLogger("school_scraper")
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

SERPER_KEY = os.environ.get("SERPER_API_KEY") or os.environ.get("OPENROUTER_API_KEY", "")
GEMINI_KEY = os.environ.get("GEMINI_API_KEY", "")
# Try 2.5-flash first, fall back to 1.5-flash if unavailable
GEMINI_URL      = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-2.5-flash:generateContent?key={GEMINI_KEY}"
GEMINI_URL_FAST = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-1.5-flash:generateContent?key={GEMINI_KEY}"

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
                  " (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Accept-Language": "en-US,en;q=0.9",
}
SESSION = requests.Session()
SESSION.headers.update(HEADERS)

# ── DB ─────────────────────────────────────────────────────────────────────────
try:
    import psycopg2, psycopg2.extras
    DB_URL = os.environ.get("VPS_PG_DSN", "postgresql://corvus:corvus-local-password@127.0.0.1:5433/careerbridge")
    def get_db(): return psycopg2.connect(DB_URL, connect_timeout=10)
    HAS_DB = True
except Exception:
    HAS_DB = False
    log.warning("No DB — results will only be printed")

def ensure_table():
    if not HAS_DB: return
    sql = """
    CREATE TABLE IF NOT EXISTS schools (
        id                    SERIAL PRIMARY KEY,
        name                  TEXT NOT NULL,
        url                   TEXT,
        enrollment_url        TEXT,
        type                  TEXT,
        evidence              TEXT,
        no_id_verification    BOOLEAN DEFAULT FALSE,
        no_transcript_required BOOLEAN DEFAULT FALSE,
        monthly_enrollment    BOOLEAN DEFAULT FALSE,
        instant_acceptance    BOOLEAN DEFAULT FALSE,
        monthly_refund        BOOLEAN DEFAULT FALSE,
        community_college     BOOLEAN DEFAULT FALSE,
        filters               TEXT[],
        source_query          TEXT,
        url_hash              TEXT UNIQUE,
        created_at            TIMESTAMPTZ DEFAULT NOW(),
        updated_at            TIMESTAMPTZ DEFAULT NOW()
    );
    CREATE INDEX IF NOT EXISTS schools_filters_idx ON schools USING GIN(filters);
    """
    try:
        with get_db() as c:
            with c.cursor() as cur:
                cur.execute(sql)
            c.commit()
        log.info("schools table ready")
    except Exception as e:
        log.warning("DB unreachable (%s) — running in dry-run mode (search + analyze only)", e)

def save_school(data: dict) -> bool:
    if not HAS_DB:
        log.info("[DRY RUN] %s", json.dumps(data, default=str)[:200])
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
        evidence              = EXCLUDED.evidence,
        no_id_verification    = EXCLUDED.no_id_verification,
        no_transcript_required= EXCLUDED.no_transcript_required,
        monthly_enrollment    = EXCLUDED.monthly_enrollment,
        instant_acceptance    = EXCLUDED.instant_acceptance,
        monthly_refund        = EXCLUDED.monthly_refund,
        community_college     = EXCLUDED.community_college,
        filters               = EXCLUDED.filters,
        updated_at            = NOW()
    RETURNING id;
    """
    try:
        with get_db() as c:
            with c.cursor() as cur:
                cur.execute(sql, {**data, "url_hash": url_hash})
                row = cur.fetchone()
            c.commit()
        return bool(row)
    except Exception as e:
        log.warning("DB save skipped (unreachable): %s — printing record instead", e)
        log.info("[DRY RUN saved] %s", json.dumps(
            {k: v for k, v in data.items() if k != "_score"}, default=str
        )[:300])
        return False

# ── Serper search ───────────────────────────────────────────────────────────────
def serper_search(query: str, n: int = 10) -> list[dict]:
    """Use Serper.dev OR fallback to DuckDuckGo lite for school URLs."""
    # Try Serper first
    serper_key = os.environ.get("SERPER_API_KEY", "")
    if serper_key:
        try:
            r = requests.post(
                "https://google.serper.dev/search",
                headers={"X-API-KEY": serper_key, "Content-Type": "application/json"},
                json={"q": query, "num": n},
                timeout=15
            )
            if r.ok:
                return [{"title": x.get("title",""), "url": x.get("link",""), "snippet": x.get("snippet","")}
                        for x in r.json().get("organic", [])]
        except Exception as e:
            log.warning("Serper error: %s", e)

    # Fallback: Gemini to suggest school URLs
    if GEMINI_KEY:
        try:
            body = {
                "contents": [{"parts": [{"text":
                    f"List 8 real US universities or community colleges that match: '{query}'. "
                    "Output a JSON array, each object with keys: name, url, enrollment_url. "
                    "Example: "
                    '[{"name":"Western Governors University","url":"https://wgu.edu",'
                    '"enrollment_url":"https://wgu.edu/admissions/apply"}] '
                    "Output ONLY the JSON array, nothing else."
                }]}],
                "generationConfig": {"temperature": 0.2, "maxOutputTokens": 1024}
            }
            raw = _call_gemini(body, timeout=30)
            if raw:
                log.debug("Gemini URL suggestion raw: %s", raw[:300])
                # Strip markdown fences
                text = raw.strip()
                if text.startswith("```"):
                    lines = text.splitlines()
                    text = "\n".join(lines[1:])
                    if "```" in text:
                        text = text[:text.rfind("```")]
                text = text.strip()
                # Try as JSON array first
                results = []
                try:
                    parsed = json.loads(text)
                    if isinstance(parsed, list):
                        for obj in parsed:
                            if isinstance(obj, dict) and obj.get("url"):
                                results.append({
                                    "title": obj.get("name", ""),
                                    "url": obj.get("url", ""),
                                    "snippet": "",
                                    "enrollment_url": obj.get("enrollment_url", "")
                                })
                except json.JSONDecodeError:
                    # Fallback: scan line by line
                    import re as _re
                    for m in _re.finditer(r'\{[^{}]+\}', text):
                        try:
                            obj = json.loads(m.group(0))
                            if obj.get("url"):
                                results.append({
                                    "title": obj.get("name", ""),
                                    "url": obj.get("url", ""),
                                    "snippet": "",
                                    "enrollment_url": obj.get("enrollment_url", "")
                                })
                        except Exception:
                            pass
                log.info("Gemini URL fallback: %d schools for query '%s'", len(results), query[:60])
                if results:
                    return results
        except Exception as e:
            log.warning("Gemini fallback: %s", e)

    # Last resort: curated seed list (only on first query to avoid duplicates)
    log.warning("No search API available — using curated seed list")
    return _curated_seed_results()

def _curated_seed_results() -> list[dict]:
    """Known US institutions commonly meeting multiple open-enrollment criteria."""
    return [
        {"title": "Western Governors University",
         "url": "https://www.wgu.edu",
         "enrollment_url": "https://www.wgu.edu/admissions/apply.html", "snippet": ""},
        {"title": "Straighterline",
         "url": "https://www.straighterline.com",
         "enrollment_url": "https://www.straighterline.com/online-courses/",  "snippet": ""},
        {"title": "Sophia Learning",
         "url": "https://www.sophia.org",
         "enrollment_url": "https://www.sophia.org/get-started", "snippet": ""},
        {"title": "Rio Salado College",
         "url": "https://www.riosalado.edu",
         "enrollment_url": "https://www.riosalado.edu/admission/apply", "snippet": ""},
        {"title": "Coastline Community College",
         "url": "https://www.coastline.edu",
         "enrollment_url": "https://www.coastline.edu/admissions/apply/", "snippet": ""},
        {"title": "Penn Foster College",
         "url": "https://www.pennfoster.edu",
         "enrollment_url": "https://www.pennfoster.edu/apply", "snippet": ""},
        {"title": "Excelsior University",
         "url": "https://www.excelsior.edu",
         "enrollment_url": "https://www.excelsior.edu/apply/", "snippet": ""},
        {"title": "Thomas Edison State University",
         "url": "https://www.tesu.edu",
         "enrollment_url": "https://www.tesu.edu/admissions/apply", "snippet": ""},
        {"title": "University of the People",
         "url": "https://www.uopeople.edu",
         "enrollment_url": "https://www.uopeople.edu/admissions/", "snippet": ""},
        {"title": "Clovis Community College",
         "url": "https://www.clovis.edu",
         "enrollment_url": "https://www.clovis.edu/admissions/", "snippet": ""},
    ]

# ── Page scraper ───────────────────────────────────────────────────────────────
def fetch_page(url: str, timeout: int = 12) -> str:
    """Fetch page text, return '' on error."""
    try:
        r = SESSION.get(url, timeout=timeout, allow_redirects=True)
        if r.ok:
            soup = BeautifulSoup(r.text, "html.parser")
            for tag in soup(["script", "style", "nav", "footer", "header"]):
                tag.decompose()
            return " ".join(soup.get_text(" ", strip=True).split())[:6000]
    except Exception as e:
        log.debug("fetch %s: %s", url, e)
    return ""

def find_enrollment_url(base_url: str, soup_text: str) -> str:
    """Find the enrollment/admissions URL on a school site."""
    patterns = [
        r"https?://[^\s\"'<>]+(?:apply|enroll|admission|register|sign-?up)[^\s\"'<>]*",
    ]
    for pat in patterns:
        m = re.search(pat, soup_text, re.IGNORECASE)
        if m:
            return m.group(0).rstrip(".,;)")
    # Guess common paths
    base = base_url.rstrip("/")
    for path in ["/apply", "/admissions/apply", "/enrollment", "/enroll", "/register"]:
        try:
            r = SESSION.head(base + path, timeout=8, allow_redirects=True)
            if r.status_code < 400:
                return base + path
        except Exception:
            pass
    return ""

# ── Evidence extractor via Gemini ─────────────────────────────────────────────
CRITERIA_PROMPT = """
You are an admissions analyst. Given the text from a school's website,
determine which of these criteria the school meets:

1. community_college — is it a community college or two-year college?
2. no_id_verification — can students enroll without submitting government-issued ID?
3. no_transcript — no high-school or prior transcripts required for enrollment?
4. monthly_enrollment — does the school accept new students every month or on a rolling basis?
5. instant_acceptance — are applications accepted/approved immediately or near-instantly?
6. monthly_refund — does the school issue tuition refunds on a monthly schedule?

Output ONLY a JSON object like:
{
  "community_college": true,
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
---
"""

def _call_gemini(body: dict, timeout: int = 30) -> str | None:
    """Call Gemini, fall back to 1.5-flash if 2.5-flash returns 503."""
    for url in (GEMINI_URL, GEMINI_URL_FAST):
        try:
            resp = requests.post(url, json=body, timeout=timeout)
            if resp.status_code == 503:
                log.warning("Gemini 503 on %s, trying fallback model", url.split("models/")[1].split(":")[0])
                continue
            resp.raise_for_status()
            return resp.json()["candidates"][0]["content"]["parts"][0]["text"]
        except Exception as e:
            log.warning("Gemini call failed (%s): %s", url.split("models/")[1].split(":")[0], e)
    return None

def analyze_school(name: str, url: str, page_text: str) -> dict:
    """Use Gemini to extract criteria from page text."""
    if not GEMINI_KEY or not page_text:
        return {}
    prompt = CRITERIA_PROMPT.replace("{TEXT}", page_text[:4000])
    body = {
        "contents": [{"parts": [{"text": prompt}]}],
        "generationConfig": {"temperature": 0.1, "maxOutputTokens": 512}
    }
    text = _call_gemini(body)
    if not text:
        return {}
    try:
        text = text.strip()
        if text.startswith("```"):
            text = "\n".join(text.splitlines()[1:])
            text = text[:text.rfind("```")] if "```" in text else text
        return json.loads(text.strip())
    except Exception as e:
        log.warning("Gemini JSON parse for %s: %s", name, e)
        return {}

# ── Heuristic fallback (no Gemini) ─────────────────────────────────────────────
ID_VERIFY_DENY = re.compile(
    r"government.?issued|photo id|driver.?licen|passport|id verification|identity verification",
    re.I
)
MONTHLY_RE = re.compile(
    r"monthly\s+(?:enrollment|intake|start|cohort|admission)|rolling\s+admission|"
    r"start\s+every\s+month|new\s+students?\s+(?:every|each)\s+month|"
    r"5\s+start\s+dates|multiple\s+start\s+dates",
    re.I
)
INSTANT_RE = re.compile(
    r"instant(?:ly)?\s+accept|immediate\s+(?:accept|enroll|decision)|"
    r"admitted\s+immediately|no\s+waiting|apply\s+and\s+start\s+today",
    re.I
)
TRANSCRIPT_DENY = re.compile(r"no\s+transcript|without\s+transcript|transcript\s+not\s+required", re.I)
TRANSCRIPT_REQ  = re.compile(r"official\s+transcript|require\s+transcript", re.I)
REFUND_RE = re.compile(r"monthly\s+refund|refund\s+schedule|pro-?rated\s+refund", re.I)
COMMUNITY_RE = re.compile(r"community\s+college|two[- ]year\s+college|2[- ]year\s+college", re.I)

def heuristic_analyze(name: str, text: str) -> dict:
    """Simple regex-based fallback when Gemini is unavailable."""
    d = {
        "community_college":     bool(COMMUNITY_RE.search(name) or COMMUNITY_RE.search(text)),
        "no_id_verification":    not bool(ID_VERIFY_DENY.search(text)),
        "no_transcript":         bool(TRANSCRIPT_DENY.search(text)) or not bool(TRANSCRIPT_REQ.search(text)),
        "monthly_enrollment":    bool(MONTHLY_RE.search(text)),
        "instant_acceptance":    bool(INSTANT_RE.search(text)),
        "monthly_refund":        bool(REFUND_RE.search(text)),
        "evidence":              "",
    }
    bits = []
    if d["monthly_enrollment"]: bits.append("rolling/monthly enrollment")
    if d["instant_acceptance"]: bits.append("instant acceptance")
    if d["no_id_verification"]: bits.append("no ID verification required")
    if d["no_transcript"]:      bits.append("no transcript needed")
    if d["monthly_refund"]:     bits.append("monthly refund policy")
    d["evidence"] = "; ".join(bits) if bits else "Enrollment terms not clearly stated"
    return d

# ── Master search queries ───────────────────────────────────────────────────────
SEARCH_QUERIES = {
    # Top priority: schools meeting ALL or most criteria at once
    "best_match": [
        "online community college monthly enrollment no ID verification no transcript instant acceptance",
        "fully online college rolling admission no government ID no transcripts monthly start date",
        "open enrollment online community college monthly refund policy instant acceptance 2024",
        "online university enroll without ID monthly intake no transcript required same-day acceptance",
    ],
    "community_college": [
        "US community college fully online open enrollment no ID verification",
        "online community college monthly enrollment 2024",
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
        "online college multiple start dates monthly 2024",
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

# ── Main scraping pipeline ─────────────────────────────────────────────────────
def scrape_for_filter(filter_name: str, custom_query: str = "") -> list[dict]:
    queries = SEARCH_QUERIES.get(filter_name, [])
    if custom_query:
        queries = [custom_query] + queries

    seen_urls: set[str] = set()
    results = []

    for query in queries[:4]:  # max 4 queries per filter
        log.info("Searching: '%s'", query)
        hits = serper_search(query, n=8)
        time.sleep(1)

        for hit in hits:
            url = hit.get("url", "")
            if not url or url in seen_urls:
                continue
            # Skip aggregators / job boards
            skip_domains = {"indeed.com","glassdoor.com","linkedin.com","reddit.com",
                            "quora.com","niche.com","collegeconfidential.com","cappex.com",
                            "unigo.com","studyportals.com"}
            if any(d in url for d in skip_domains):
                continue
            seen_urls.add(url)

            name = hit.get("title", url)[:100]
            log.info("  → %s", name[:60])

            # Fetch enrollment page if we have one
            enrollment_url = hit.get("enrollment_url", "") or find_enrollment_url(url, hit.get("snippet",""))
            page_text      = fetch_page(enrollment_url or url)
            time.sleep(0.5)

            # Analyze
            if GEMINI_KEY:
                analysis = analyze_school(name, url, page_text)
            else:
                analysis = heuristic_analyze(name, page_text)

            if not analysis:
                analysis = heuristic_analyze(name, page_text)

            # Build active filters list
            active_filters = []
            flag_map = {
                "community_college":    "community_college",
                "no_id_verification":   "no_id_verification",
                "no_transcript":        "no_transcript_required",
                "monthly_enrollment":   "monthly_enrollment",
                "instant_acceptance":   "instant_acceptance",
                "monthly_refund":       "monthly_refund",
            }
            for k, col in flag_map.items():
                if analysis.get(k):
                    active_filters.append(k)

            criteria_score = len(active_filters)
            school = {
                "name":                   name,
                "url":                    url,
                "enrollment_url":         enrollment_url or url,
                "type":                   "Community College" if analysis.get("community_college") else "University/College",
                "evidence":               analysis.get("evidence", ""),
                "no_id_verification":     bool(analysis.get("no_id_verification")),
                "no_transcript_required": bool(analysis.get("no_transcript")),
                "monthly_enrollment":     bool(analysis.get("monthly_enrollment")),
                "instant_acceptance":     bool(analysis.get("instant_acceptance")),
                "monthly_refund":         bool(analysis.get("monthly_refund")),
                "community_college":      bool(analysis.get("community_college")),
                "filters":                active_filters,
                "source_query":           query,
                "_score":                 criteria_score,  # in-memory only, for sorting
            }
            results.append(school)
            saved = save_school(school)
            log.info("    Score %d/6 — Filters: %s — saved=%s",
                     criteria_score, active_filters or ["none"], saved)

    return results

# ── CLI ────────────────────────────────────────────────────────────────────────
def main():
    parser = argparse.ArgumentParser(description="School Enrollment Scraper")
    parser.add_argument("--filter", choices=list(SEARCH_QUERIES.keys()) + ["all"],
                        default="all", help="Which filter to scrape for (best_match runs first when all)")
    parser.add_argument("--custom", default="", help="Custom search query")
    parser.add_argument("--report", action="store_true", help="Print report at end")
    args = parser.parse_args()

    ensure_table()

    if args.filter == "all":
        # Run best_match first so top schools are found early
        filters_to_run = ["best_match"] + [k for k in SEARCH_QUERIES if k != "best_match"]
    else:
        filters_to_run = [args.filter]
    all_results = []

    for filt in filters_to_run:
        log.info("=" * 60)
        log.info("Scraping filter: %s", filt)
        log.info("=" * 60)
        results = scrape_for_filter(filt, args.custom)
        all_results.extend(results)
        time.sleep(2)

    # ── Report ─────────────────────────────────────────────────────────────────
    if args.report or True:  # always print summary
        # Sort by criteria score descending — all-criteria winners first
        all_results.sort(key=lambda s: s.get("_score", 0), reverse=True)

        print("\n" + "=" * 70)
        print("SCHOOL SCRAPER REPORT")
        print(f"Generated: {datetime.utcnow().strftime('%Y-%m-%d %H:%M UTC')}")
        print("=" * 70)
        print(f"Total schools found: {len(all_results)}")

        # Tier breakdown
        tiers = {6: [], 5: [], 4: [], 3: [], 2: [], 1: [], 0: []}
        for s in all_results:
            tiers.setdefault(s.get("_score", 0), []).append(s)

        print("\n=== Schools by criteria score (6 = meets ALL) ===\n")
        for score in sorted(tiers.keys(), reverse=True):
            schools = tiers[score]
            if not schools:
                continue
            marker = "[BEST]" if score == 6 else ("[GOOD]" if score >= 4 else "     ")
            print(f"  {marker} Score {score}/6 — {len(schools)} school(s)")
            for s in schools[:5]:
                print(f"     • {s['name'][:65]}")
                print(f"       URL: {s['url']}")
                if s.get("evidence"):
                    print(f"       Evidence: {s['evidence'][:100]}")
                if s.get("filters"):
                    print(f"       Criteria: {', '.join(s['filters'])}")

        by_filter: dict[str, list] = {}
        for s in all_results:
            for f in (s.get("filters") or []):
                by_filter.setdefault(f, []).append(s)

        print("\nBy filter (top 3 per category, sorted by score):")
        for filt, schools in by_filter.items():
            schools_sorted = sorted(schools, key=lambda s: s.get("_score", 0), reverse=True)
            print(f"\n  [{filt.upper()}] — {len(schools)} schools")
            for s in schools_sorted[:3]:
                print(f"    • {s['name'][:60]}  (score {s.get('_score',0)}/6)")
                print(f"      {s['url']}")

        print("\n" + "=" * 70)
        print("Full results saved to DB (schools table). Sorted by criteria score.")

if __name__ == "__main__":
    main()
