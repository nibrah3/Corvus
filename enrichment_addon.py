"""
BROKEN + SUPERSEDED — file is damaged (imports missing from top).
Active job enrichment logic lives in scripts/enrich_jobs.py.
Do not import or run this file.
"""
# fmt: off  # noqa
import os, logging, requests
log = logging.getLogger(__name__)

SERPER_API_KEY = os.getenv("SERPER_API_KEY", "")
SERPER_BASE    = os.getenv("SERPER_BASE_URL", "https://google.serper.dev")

ATS_SLUG_PATTERNS = [
    (r"greenhouse\.io/([^/?#]+)/jobs",    "greenhouse"),
    (r"boards\.greenhouse\.io/([^/?#]+)", "greenhouse"),
    (r"lever\.co/([^/?#]+)",              "lever"),
    (r"jobs\.lever\.co/([^/?#]+)",        "lever"),
]


def serper_search(query, num=5):
    if not SERPER_API_KEY:
        return []
    try:
        r = requests.post(
            f"{SERPER_BASE}/search",
            headers={"X-API-KEY": SERPER_API_KEY, "Content-Type": "application/json"},
            json={"q": query, "num": num},
            timeout=10,
        )
        return r.json().get("organic", [])
    except Exception as e:
        log.warning(f"Serper: {e}")
        return []


def detect_ats(results):
    import re as _re
    for item in results:
        url = item.get("link", "")
        for pat, ats in ATS_SLUG_PATTERNS:
            m = _re.search(pat, url)
            if m:
                return ats, m.group(1).rstrip("/")
    return None, None


def enrich_lever(company, slug):
    log.info(f"Lever: {company}/{slug}")
    try:
        r = requests.get(f"https://api.lever.co/v0/postings/{slug}?mode=json", timeout=15)
        if r.status_code != 200:
            return 0
        jobs = r.json() if isinstance(r.json(), list) else []
        stored = sum(1 for j in jobs if upsert(
            url=j.get("hostedUrl") or j.get("applyUrl"),
            title=j.get("text", company),
            company=company,
            description={"location": j.get("categories", {}).get("location"),
                         "team": j.get("categories", {}).get("team")},
            source="lever",
        ))
        log.info(f"{company} (Lever): {len(jobs)} total, {stored} new")
        return stored
    except Exception as e:
        log.error(f"{company} Lever: {e}")
        return 0


def discover_company_careers(company_name):
    """
    Career-page-first lookup for a newly discovered company.
    1. Serper search for Greenhouse/Lever ATS
    2. If found -> pull via ATS API
    3. Else -> Firecrawl their careers page
    """
    log.info(f"Career lookup: {company_name}")

    results = serper_search(
        f'"{company_name}" site:greenhouse.io OR site:lever.co OR site:boards.greenhouse.io',
    )
    ats_type, slug = detect_ats(results)

    if ats_type == "greenhouse" and slug:
        log.info(f"{company_name} -> Greenhouse/{slug}")
        return enrich_greenhouse(company_name, slug)
    if ats_type == "lever" and slug:
        log.info(f"{company_name} -> Lever/{slug}")
        return enrich_lever(company_name, slug)

    domain = company_name.lower().replace(" ", "").replace(".", "")
    results2 = serper_search(f'"{company_name}" careers apply jobs', num=3)
    if results2:
        career_url = results2[0].get("link", "")
        if career_url and "http" in career_url:
            log.info(f"{company_name} -> Firecrawl {career_url}")
            stored, _ = enrich_firecrawl(company_name, career_url)
            return stored

    log.info(f"{company_name}: no career page found")
    return 0
