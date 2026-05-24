"""
serper_graph_expand.py — Expand ATS probe coverage via Serper.

Reads distinct company names from VPS postgres (jobs table), searches Serper
for each company's careers page, and pushes discovered URLs as career_page
probe jobs into the VPS crawlee API so CareerPageScraper can check them.

Tracks already-explored companies in postgres (probe_log table) to avoid
duplicate Serper spend.

Requirements:
  - VPS SSH tunnels active: run powershell D:\\cb-core\\scripts\\vps_tunnel.ps1
    (Redis:6380, Postgres:5433, Crawlee:3101)
  - D:\\cb-core\\.env with SERPER_API_KEY

Usage:
  python scripts/serper_graph_expand.py [--limit 50] [--dry-run]
"""
from __future__ import annotations

import argparse
import json
import logging
import os
import re
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Optional

CB_DIR = Path(__file__).resolve().parent.parent

# ── Config ─────────────────────────────────────────────────────────────────────

def _load_env() -> None:
    p = CB_DIR / ".env"
    if p.exists():
        for line in p.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, _, v = line.partition("=")
                os.environ.setdefault(k.strip(), v.strip())

_load_env()

SERPER_KEY   = os.environ.get("SERPER_API_KEY", "")
# On desktop: uses tunnel ports (5433/3101). On VPS: uses POSTGRES_DSN / direct 3100.
PG_DSN       = (os.environ.get("POSTGRES_DSN") or
                os.environ.get("VPS_PG_DSN",
                "postgresql://corvus:corvus-local-password@127.0.0.1:5433/careerbridge"))
CRAWLEE_URL  = (os.environ.get("CRAWLEE_URL") or
                os.environ.get("VPS_CRAWLEE_URL", "http://127.0.0.1:3101"))

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s: %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger(__name__)

# ── Serper ─────────────────────────────────────────────────────────────────────

_CAREERS_PATTERNS = re.compile(
    r"/(careers|jobs|work-with-us|join-us|join|opportunities|vacancies|"
    r"open-positions|work-here|employment|talent)(/|$)",
    re.IGNORECASE,
)

def _serper_search(query: str) -> list[dict]:
    if not SERPER_KEY:
        raise RuntimeError("SERPER_API_KEY not set in .env")
    body = json.dumps({"q": query, "gl": "us", "num": 10}).encode()
    req  = urllib.request.Request(
        "https://google.serper.dev/search",
        data=body,
        headers={
            "X-API-KEY":     SERPER_KEY,
            "Content-Type":  "application/json",
        },
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=15) as r:
        return json.loads(r.read()).get("organic", [])


def _extract_careers_url(results: list[dict], company: str) -> Optional[str]:
    """Return the best careers page URL from Serper organic results."""
    company_lower = company.lower()

    for r in results:
        url  = r.get("link", "")
        link = r.get("link", "").lower()
        title = r.get("title", "").lower()

        # Must mention the company in title/URL and look like a careers page
        company_slug = re.sub(r"[^a-z0-9]", "", company_lower)
        url_slug     = re.sub(r"[^a-z0-9]", "", link)

        if company_slug not in url_slug[:60]:
            continue
        if _CAREERS_PATTERNS.search(url) or "careers" in title or "jobs" in title:
            return url

    # Fallback: first result that looks like a careers page regardless of domain
    for r in results:
        url = r.get("link", "")
        if _CAREERS_PATTERNS.search(url):
            return url

    return None

# ── Postgres ───────────────────────────────────────────────────────────────────

def _pg_connect():
    try:
        import psycopg2  # type: ignore
        return psycopg2.connect(PG_DSN, connect_timeout=8)
    except ImportError:
        raise RuntimeError("psycopg2 not installed: pip install psycopg2-binary")


def _ensure_tables(conn) -> None:
    with conn.cursor() as cur:
        cur.execute("""
            CREATE TABLE IF NOT EXISTS probe_log (
                company TEXT PRIMARY KEY,
                careers_url TEXT,
                searched_at TIMESTAMP DEFAULT NOW()
            )
        """)
        cur.execute("""
            CREATE TABLE IF NOT EXISTS discovered_platforms (
                id                   SERIAL PRIMARY KEY,
                company              TEXT NOT NULL,
                careers_url          TEXT NOT NULL UNIQUE,
                source               TEXT,
                category             TEXT,
                ats_type             TEXT DEFAULT 'firecrawl',
                ats_slug             TEXT,
                check_interval_hours INT DEFAULT 24,
                last_checked_at      TIMESTAMP,
                last_found_jobs      INT DEFAULT 0,
                consecutive_empty    INT DEFAULT 0,
                is_active            BOOLEAN DEFAULT TRUE,
                about                TEXT,
                discovered_at        TIMESTAMP DEFAULT NOW()
            )
        """)
    conn.commit()


# Keep old name as alias so nothing else breaks
def _ensure_probe_log(conn) -> None:
    _ensure_tables(conn)


def _get_unexplored_companies(conn, limit: int) -> list[str]:
    with conn.cursor() as cur:
        cur.execute("""
            SELECT DISTINCT company FROM jobs
            WHERE company IS NOT NULL AND company != ''
              AND company NOT IN (SELECT company FROM probe_log)
            ORDER BY company
            LIMIT %s
        """, (limit,))
        return [row[0] for row in cur.fetchall()]


def _record_probe(conn, company: str, careers_url: Optional[str]) -> None:
    with conn.cursor() as cur:
        cur.execute("""
            INSERT INTO probe_log (company, careers_url)
            VALUES (%s, %s)
            ON CONFLICT (company) DO UPDATE
              SET careers_url = EXCLUDED.careers_url,
                  searched_at = NOW()
        """, (company, careers_url))
    conn.commit()


def _save_discovered_platform(conn, company: str, careers_url: str) -> None:
    """Register the platform permanently so enrichment picks it up on every cycle."""
    with conn.cursor() as cur:
        cur.execute("""
            INSERT INTO discovered_platforms (company, careers_url, source)
            VALUES (%s, %s, 'serper_expand')
            ON CONFLICT (careers_url) DO UPDATE
              SET company = EXCLUDED.company,
                  source  = COALESCE(discovered_platforms.source, EXCLUDED.source)
        """, (company, careers_url))
    conn.commit()

# ── Crawlee trigger ────────────────────────────────────────────────────────────

def _trigger_career_scrape(url: str) -> bool:
    """Push a URL to the VPS CareerPageScraper via the Crawlee API."""
    body = json.dumps({"url": url, "limit": 20}).encode()
    req  = urllib.request.Request(
        f"{CRAWLEE_URL}/scrape/career_pages",
        data=body,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=10) as r:
            d = json.loads(r.read())
            return d.get("success", False)
    except Exception as e:
        log.warning("Crawlee trigger failed for %s: %s", url, e)
        return False

# ── Main ───────────────────────────────────────────────────────────────────────

def run(limit: int = 50, dry_run: bool = False) -> None:
    conn = _pg_connect()
    _ensure_tables(conn)

    companies = _get_unexplored_companies(conn, limit)
    log.info("Found %d unexplored companies (limit=%d)", len(companies), limit)

    found = skipped = errors = 0

    for company in companies:
        query = f'"{company}" careers jobs'
        try:
            results = _serper_search(query)
            url = _extract_careers_url(results, company)

            if url:
                log.info("[FOUND] %-40s -> %s", company, url)
                found += 1
                if not dry_run:
                    _record_probe(conn, company, url)
                    _save_discovered_platform(conn, company, url)
                    _trigger_career_scrape(url)
            else:
                log.debug("[SKIP]  %-40s (no careers URL in results)", company)
                skipped += 1
                if not dry_run:
                    _record_probe(conn, company, None)

            time.sleep(0.4)  # ~2.5 req/s — well within Serper rate limits

        except Exception as e:
            log.warning("[ERR]  %-40s: %s", company, e)
            errors += 1

    conn.close()
    log.info("Done. Found=%d  Skipped=%d  Errors=%d  dry_run=%s",
             found, skipped, errors, dry_run)


if __name__ == "__main__":
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--limit",   type=int, default=50,
                   help="Max companies to process per run (default 50)")
    p.add_argument("--dry-run", action="store_true",
                   help="Search and print results but do not write to postgres or trigger crawlee")
    args = p.parse_args()

    if not SERPER_KEY:
        log.error("SERPER_API_KEY not set. Add it to D:\\cb-core\\.env")
        sys.exit(1)

    run(limit=args.limit, dry_run=args.dry_run)
