"""
Round 1: US College Scorecard API — identify candidate institutions.

API docs: https://collegescorecard.ed.gov/data/documentation/
Free key: https://api.data.ed.gov/student/v1/
"""
from __future__ import annotations

import logging
import os
import time
from typing import Optional

import requests

log = logging.getLogger(__name__)

_BASE = "https://api.data.ed.gov/student/v1/schools.json"
_KEY  = os.environ.get("SCORECARD_API_KEY") or os.environ.get("COLLEGE_SCORECARD_API_KEY", "")

# Fields to retrieve from the API
_FIELDS = ",".join([
    "id",
    "school.name",
    "school.school_url",
    "school.city",
    "school.state",
    "school.online_only",
    "school.predominant_degree",
    "school.open_admissions_policy",
    "school.ownership",
])

# Map our filter names to Scorecard query params for pre-filtering candidates
_FILTER_PARAMS: dict[str, dict] = {
    "community_college": {"school.predominant_degree": 2},
    "no_id_verification": {"school.online_only": 1},
    "no_transcript":      {"school.open_admissions_policy": 1},
    "monthly_enrollment": {"school.online_only": 1},
    "instant_acceptance": {"school.open_admissions_policy": 1},
    "monthly_refund":     {"school.online_only": 1},
}


def _page(params: dict, page: int, per_page: int = 100) -> list[dict]:
    if not _KEY:
        log.warning("COLLEGE_SCORECARD_API_KEY not set")
        return []
    try:
        r = requests.get(
            _BASE,
            params={**params, "fields": _FIELDS, "per_page": per_page,
                    "page": page, "api_key": _KEY},
            timeout=20,
        )
        r.raise_for_status()
        return r.json().get("results", [])
    except Exception as e:
        log.warning("Scorecard API page %d failed: %s", page, e)
        return []


def _norm(raw: dict) -> Optional[dict]:
    """Normalise a raw API result into a clean school dict. Returns None if URL missing."""
    url = (raw.get("school.school_url") or "").strip().lower()
    if not url:
        return None
    if not url.startswith("http"):
        url = "https://" + url
    name = (raw.get("school.name") or "").strip()
    if not name:
        return None
    degree = raw.get("school.predominant_degree")
    online  = bool(raw.get("school.online_only"))
    return {
        "scorecard_id":   raw.get("id"),
        "name":           name,
        "url":            url,
        "city":           raw.get("school.city", ""),
        "state":          raw.get("school.state", ""),
        "online_only":    online,
        "open_admissions":bool(raw.get("school.open_admissions_policy")),
        "is_community_college": degree == 2,
        "ownership":      raw.get("school.ownership"),  # 1=public, 2=nonprofit, 3=for-profit
    }


def fetch_candidates(filters: list[str], limit: int = 100) -> list[dict]:
    """
    Query College Scorecard for schools matching the requested filters.
    Returns up to `limit` unique school dicts, deduped by scorecard_id.
    """
    if not _KEY:
        log.warning("COLLEGE_SCORECARD_API_KEY missing — skipping gov API round")
        return []

    # Build query set: always include online + open-admissions searches,
    # plus filter-specific param overrides
    query_params: list[dict] = [
        {"school.online_only": 1, "school.operating": 1},
        {"school.open_admissions_policy": 1, "school.operating": 1},
    ]
    for f in (filters or []):
        extra = _FILTER_PARAMS.get(f)
        if extra:
            p = {**extra, "school.operating": 1}
            if p not in query_params:
                query_params.append(p)

    seen_ids: set = set()
    results: list[dict] = []

    for params in query_params:
        page = 0
        while len(results) < limit:
            batch = _page(params, page)
            if not batch:
                break
            for raw in batch:
                sid = raw.get("id")
                if sid in seen_ids:
                    continue
                seen_ids.add(sid)
                normed = _norm(raw)
                if normed:
                    results.append(normed)
                    if len(results) >= limit:
                        break
            if len(batch) < 100:
                break
            page += 1
            time.sleep(0.3)

    log.info("Gov API: %d unique candidates across %d queries", len(results), len(query_params))
    return results[:limit]
