"""
reliability.py — Circuit breaker, exponential-backoff retry, and dead letter queue.

Single responsibility: contain all failure-tolerance logic so pipelines stay clean.

Usage:
    from careerbridge.reliability import CircuitBreaker, retry_with_backoff, DeadLetterQueue

    breaker = CircuitBreaker("linkedin.com", failure_threshold=5, recovery_s=120)

    @retry_with_backoff(max_attempts=3)
    def do_something(): ...

    dlq = DeadLetterQueue(db_path)
    dlq.push(job_id, reason, payload)
"""
from __future__ import annotations

import functools
import json
import logging
import sqlite3
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from threading import Lock
from typing import Callable, Any

log = logging.getLogger(__name__)


# ── Circuit Breaker ───────────────────────────────────────────────────────────

class CircuitOpen(Exception):
    """Raised when a circuit is open (site is failing; skip immediately)."""


@dataclass
class _CircuitState:
    failures:      int   = 0
    opened_at:     float = 0.0   # monotonic time when circuit opened
    half_open_ok:  bool  = False  # True when we're testing recovery


class CircuitBreaker:
    """
    Per-site circuit breaker.

    States:
      CLOSED  → normal, failures accumulate
      OPEN    → fail fast (raises CircuitOpen) until recovery_s elapsed
      HALF-OPEN → one trial request; success → CLOSED, failure → OPEN again
    """

    def __init__(
        self,
        name: str,
        failure_threshold: int = 5,
        recovery_s: float = 120.0,
    ) -> None:
        self.name = name
        self._threshold = failure_threshold
        self._recovery  = recovery_s
        self._state     = _CircuitState()
        self._lock      = Lock()

    def call(self, fn: Callable, *args, **kwargs) -> Any:
        with self._lock:
            st = self._state
            if st.failures >= self._threshold:
                elapsed = time.monotonic() - st.opened_at
                if elapsed < self._recovery:
                    raise CircuitOpen(
                        f"Circuit OPEN for {self.name!r} "
                        f"({self._recovery - elapsed:.0f}s remaining)"
                    )
                # Enter half-open: allow one probe
                st.half_open_ok = True

        try:
            result = fn(*args, **kwargs)
            with self._lock:
                if self._state.half_open_ok or self._state.failures > 0:
                    log.info("Circuit CLOSED for %r after recovery.", self.name)
                self._state = _CircuitState()  # reset
            return result
        except CircuitOpen:
            raise
        except Exception as exc:
            with self._lock:
                self._state.failures += 1
                self._state.opened_at = time.monotonic()
                self._state.half_open_ok = False
                if self._state.failures >= self._threshold:
                    log.warning(
                        "Circuit OPENED for %r after %d failures. "
                        "Recovery in %ds.",
                        self.name, self._state.failures, int(self._recovery),
                    )
            raise


# ── Exponential-backoff retry decorator ──────────────────────────────────────

def retry_with_backoff(
    max_attempts: int = 3,
    base_delay: float = 1.0,
    max_delay: float = 60.0,
    exceptions: tuple = (Exception,),
):
    """
    Decorator: retry up to max_attempts times with exponential backoff.
    Skips retry for CircuitOpen (let the breaker decide).
    """
    def decorator(fn: Callable) -> Callable:
        @functools.wraps(fn)
        def wrapper(*args, **kwargs):
            delay = base_delay
            for attempt in range(1, max_attempts + 1):
                try:
                    return fn(*args, **kwargs)
                except CircuitOpen:
                    raise   # don't retry circuit-open — it's intentional
                except exceptions as exc:
                    if attempt == max_attempts:
                        raise
                    jitter = delay * 0.1 * (2 * __import__('random').random() - 1)
                    sleep  = min(max_delay, delay + jitter)
                    log.warning(
                        "%s failed (attempt %d/%d): %s — retrying in %.1fs",
                        fn.__name__, attempt, max_attempts, exc, sleep,
                    )
                    time.sleep(sleep)
                    delay = min(max_delay, delay * 2)
        return wrapper
    return decorator


# ── Dead Letter Queue ─────────────────────────────────────────────────────────

class DeadLetterQueue:
    """
    SQLite-backed dead letter queue for jobs that exhausted all retries.
    Schema is auto-created on first use.
    """

    def __init__(self, db_path: str | Path) -> None:
        self._db = str(db_path)
        self._init()

    def _init(self) -> None:
        with sqlite3.connect(self._db) as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS dead_letter_jobs (
                    id          INTEGER PRIMARY KEY AUTOINCREMENT,
                    created_at  TEXT    NOT NULL,
                    job_id      TEXT    NOT NULL,
                    reason      TEXT    NOT NULL,
                    payload     TEXT    NOT NULL,
                    resolved    INTEGER NOT NULL DEFAULT 0
                )
            """)
            conn.commit()

    def push(self, job_id: str | int, reason: str, payload: dict) -> None:
        now = datetime.now(timezone.utc).isoformat()
        with sqlite3.connect(self._db) as conn:
            conn.execute(
                "INSERT INTO dead_letter_jobs (created_at, job_id, reason, payload) "
                "VALUES (?, ?, ?, ?)",
                (now, str(job_id), reason, json.dumps(payload)),
            )
            conn.commit()
        log.error("DLQ: job %s → %s", job_id, reason)

    def pending(self) -> list[dict]:
        with sqlite3.connect(self._db) as conn:
            conn.row_factory = sqlite3.Row
            rows = conn.execute(
                "SELECT * FROM dead_letter_jobs WHERE resolved=0 ORDER BY created_at"
            ).fetchall()
        return [dict(r) for r in rows]

    def resolve(self, dlq_id: int) -> None:
        with sqlite3.connect(self._db) as conn:
            conn.execute(
                "UPDATE dead_letter_jobs SET resolved=1 WHERE id=?", (dlq_id,)
            )
            conn.commit()
