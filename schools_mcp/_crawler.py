"""
Round 2: Crawl each school's admissions/enrollment page for criteria analysis.
Primary: Firecrawl API.  Fallback: requests + BeautifulSoup.
"""
from __future__ import annotations

import logging
import os
import re
import time
from typing import Optional

import requests
from bs4 import BeautifulSoup

log = logging.getLogger(__name__)

# Self-hosted Firecrawl at localhost:7788 (SSH tunnel → VPS).
# Override with FIRECRAWL_API env var; FIRECRAWL_API_KEY only needed for cloud API.
_FIRECRAWL_BASE = os.environ.get("FIRECRAWL_API", "http://localhost:7788/v1")
_FIRECRAWL_KEY  = os.environ.get("FIRECRAWL_API_KEY", "")

# Paths to probe for enrollment/admissions pages
_ENROLL_PATHS = [
    "/admissions", "/admissions/apply", "/apply", "/enrollment",
    "/enroll", "/register", "/get-started", "/admissions/requirements",
    "/undergraduate/admissions", "/future-students",
]

_ENROLL_LINK_RE = re.compile(
    r'(?:href=["\'])([^"\']*(?:apply|enroll|admission|register|get-started)[^"\']*)',
    re.I,
)

_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "en-US,en;q=0.9",
}
_SESSION = requests.Session()
_SESSION.headers.update(_HEADERS)


# ── Firecrawl ─────────────────────────────────────────────────────────────────

def _firecrawl_scrape(url: str, timeout: int = 30) -> Optional[str]:
    """Scrape a single URL via self-hosted Firecrawl, return markdown text or None."""
    try:
        headers = {"Content-Type": "application/json"}
        if _FIRECRAWL_KEY:
            headers["Authorization"] = f"Bearer {_FIRECRAWL_KEY}"
        r = requests.post(
            f"{_FIRECRAWL_BASE}/scrape",
            headers=headers,
            json={
                "url": url,
                "formats": ["markdown"],
                "onlyMainContent": True,
                "waitFor": 2000,
                "timeout": timeout * 1000,
            },
            timeout=timeout + 5,
        )
        if not r.ok:
            log.debug("Firecrawl %s → %d", url, r.status_code)
            return None
        data = r.json().get("data", {})
        md = data.get("markdown") or data.get("content") or ""
        return md if len(md) > 100 else None
    except Exception as e:
        log.debug("Firecrawl error for %s: %s", url, e)
        return None


# ── BS4 fallback ──────────────────────────────────────────────────────────────

def _bs4_scrape(url: str) -> str:
    try:
        r = _SESSION.get(url, timeout=15, allow_redirects=True)
        if not r.ok:
            return ""
        soup = BeautifulSoup(r.text, "html.parser")
        for tag in soup(["script", "style", "nav", "footer", "header", "aside"]):
            tag.decompose()
        return " ".join(soup.get_text(" ", strip=True).split())[:8000]
    except Exception as e:
        log.debug("BS4 fetch %s: %s", url, e)
        return ""


def _find_enroll_url(base_url: str, home_text: str) -> Optional[str]:
    """Try to locate enrollment/admissions URL from home page content."""
    # 1. Extract from page links
    base = base_url.rstrip("/")
    for m in _ENROLL_LINK_RE.finditer(home_text):
        candidate = m.group(1)
        if not candidate.startswith("http"):
            candidate = base + "/" + candidate.lstrip("/")
        try:
            h = _SESSION.head(candidate, timeout=6, allow_redirects=True)
            if h.status_code < 400:
                return candidate
        except Exception:
            pass

    # 2. Probe common paths
    for path in _ENROLL_PATHS:
        try:
            h = _SESSION.head(base + path, timeout=6, allow_redirects=True)
            if h.status_code < 400:
                return base + path
        except Exception:
            pass

    return None


# ── Public API ────────────────────────────────────────────────────────────────

def crawl_school(school: dict) -> dict:
    """
    Crawl a school's home page + enrollment/admissions page.
    Returns the school dict enriched with:
        'crawled_text'    — combined text for criteria analysis
        'enrollment_url'  — resolved enrollment page URL (or '')
    """
    base_url = school["url"]

    # ── Home page ─────────────────────────────────────────────────────────────
    home_text = _firecrawl_scrape(base_url) or _bs4_scrape(base_url)
    time.sleep(0.3)

    # ── Enrollment page ───────────────────────────────────────────────────────
    enrollment_url = _find_enroll_url(base_url, home_text)
    enroll_text = ""
    if enrollment_url and enrollment_url != base_url:
        enroll_text = _firecrawl_scrape(enrollment_url) or _bs4_scrape(enrollment_url)
        time.sleep(0.3)

    # Combine, weight enrollment page more by placing it first
    combined = "\n\n".join(filter(None, [enroll_text, home_text]))[:10000]

    return {
        **school,
        "crawled_text":   combined,
        "enrollment_url": enrollment_url or "",
    }
