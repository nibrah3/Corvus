"""Database helpers: save schools to Postgres, dedup checks."""
from __future__ import annotations

import hashlib
import logging
import os
from datetime import datetime, timedelta, timezone
from typing import Optional

log = logging.getLogger(__name__)

_DSN = os.environ.get(
    "VPS_PG_DSN",
    "postgresql://corvus:corvus-local-password@127.0.0.1:5433/careerbridge",
)

try:
    import psycopg2
    import psycopg2.extras
    _HAS_DB = True
except ImportError:
    _HAS_DB = False
    log.warning("psycopg2 not installed — DB operations disabled")


def _connect():
    return psycopg2.connect(_DSN, connect_timeout=10)


def url_hash(url: str) -> str:
    return hashlib.md5(url.encode()).hexdigest()


def ensure_table() -> None:
    if not _HAS_DB:
        return
    sql = """
    CREATE TABLE IF NOT EXISTS schools (
        id                     SERIAL PRIMARY KEY,
        name                   TEXT NOT NULL,
        url                    TEXT,
        enrollment_url         TEXT,
        type                   TEXT,
        evidence               JSONB,
        no_id_verification     BOOLEAN DEFAULT FALSE,
        no_transcript_required BOOLEAN DEFAULT FALSE,
        monthly_enrollment     BOOLEAN DEFAULT FALSE,
        instant_acceptance     BOOLEAN DEFAULT FALSE,
        monthly_refund         BOOLEAN DEFAULT FALSE,
        community_college      BOOLEAN DEFAULT FALSE,
        filters                TEXT[],
        criteria_score         INT DEFAULT 0,
        source                 TEXT DEFAULT 'schools_mcp',
        source_url             TEXT,
        url_hash               TEXT UNIQUE,
        created_at             TIMESTAMPTZ DEFAULT NOW(),
        updated_at             TIMESTAMPTZ DEFAULT NOW()
    );
    ALTER TABLE schools ADD COLUMN IF NOT EXISTS source_url TEXT;
    CREATE INDEX IF NOT EXISTS schools_filters_idx ON schools USING GIN(filters);
    CREATE INDEX IF NOT EXISTS schools_score_idx   ON schools (criteria_score DESC);
    """
    try:
        with _connect() as c:
            with c.cursor() as cur:
                cur.execute(sql)
            c.commit()
    except Exception as e:
        log.warning("ensure_table failed: %s", e)


def was_recently_processed(url: str, within_days: int = 7) -> bool:
    """Return True if this URL was already saved within the last N days."""
    if not _HAS_DB:
        return False
    try:
        cutoff = datetime.now(timezone.utc) - timedelta(days=within_days)
        with _connect() as c:
            with c.cursor() as cur:
                cur.execute(
                    "SELECT 1 FROM schools WHERE url_hash=%s AND updated_at > %s",
                    (url_hash(url), cutoff),
                )
                return cur.fetchone() is not None
    except Exception as e:
        log.debug("dedup check failed: %s", e)
        return False


def save(school: dict) -> bool:
    """Upsert school record. Returns True on success."""
    evidence = school.get("evidence", {})
    row = {
        "name":                   school["name"],
        "url":                    school["url"],
        "enrollment_url":         school.get("enrollment_url", ""),
        "type":                   "Community College" if school.get("community_college") else "University/College",
        "evidence":               psycopg2.extras.Json(evidence) if _HAS_DB else evidence,
        "no_id_verification":     bool(school.get("no_id_verification")),
        "no_transcript_required": bool(school.get("no_transcript_required")),
        "monthly_enrollment":     bool(school.get("monthly_enrollment")),
        "instant_acceptance":     bool(school.get("instant_acceptance")),
        "monthly_refund":         bool(school.get("monthly_refund")),
        "community_college":      bool(school.get("community_college")),
        "filters":                school.get("filters", []),
        "criteria_score":         school.get("criteria_score", 0),
        "source_url":             school.get("source_url") or None,
        "url_hash":               url_hash(school["url"]),
    }
    if not _HAS_DB:
        log.info("[DRY RUN] %s — score %d — filters: %s",
                 row["name"][:50], row["criteria_score"], row["filters"])
        return True
    sql = """
    INSERT INTO schools (
        name, url, enrollment_url, type, evidence,
        no_id_verification, no_transcript_required, monthly_enrollment,
        instant_acceptance, monthly_refund, community_college,
        filters, criteria_score, source_url, url_hash, updated_at
    ) VALUES (
        %(name)s, %(url)s, %(enrollment_url)s, %(type)s, %(evidence)s,
        %(no_id_verification)s, %(no_transcript_required)s, %(monthly_enrollment)s,
        %(instant_acceptance)s, %(monthly_refund)s, %(community_college)s,
        %(filters)s, %(criteria_score)s, %(source_url)s, %(url_hash)s, NOW()
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
        criteria_score         = EXCLUDED.criteria_score,
        source_url             = COALESCE(EXCLUDED.source_url, schools.source_url),
        updated_at             = NOW()
    RETURNING id;
    """
    try:
        with _connect() as c:
            with c.cursor() as cur:
                cur.execute(sql, row)
                result = cur.fetchone()
            c.commit()
        return bool(result)
    except Exception as e:
        log.warning("DB save failed for %s: %s", row["name"][:50], e)
        return False
