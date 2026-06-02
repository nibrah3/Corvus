"""
raw_listener.py — Redis pub/sub listener that fires the Claude Code gate
immediately when VPS Crawlee signals new raw discoveries.

The VPS discover_and_queue.py publishes to 'corvus:raw_ready' after each
discovery run. This listener receives that signal and launches:
    claude --print -p @D:\cb-core\prompts\skill_gate_discoveries.md

Also polls 'corvus:raw_ready_queue' (a Redis list) as a fallback in case
the pub/sub message was missed (e.g. listener was restarted).

Run this as a background process via the CareerBridge-RawListener Windows Task.
Restarts automatically on disconnect.
"""
from __future__ import annotations

import logging
import os
import subprocess
import sys
import time
from pathlib import Path

CB_DIR   = Path(__file__).resolve().parent.parent
SKILL    = CB_DIR / "prompts" / "skill_gate_discoveries.md"
CLAUDE   = r"C:\Users\HP\AppData\Roaming\npm\claude.cmd"
LOG_FILE = CB_DIR / "logs" / "raw_listener.log"

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
    handlers=[
        logging.StreamHandler(sys.stdout),
        logging.FileHandler(LOG_FILE, encoding="utf-8"),
    ],
)
log = logging.getLogger("raw_listener")

for _line in (CB_DIR / ".env").read_text(encoding="utf-8").splitlines():
    if "=" in _line and not _line.startswith("#"):
        _k, _, _v = _line.partition("=")
        if _k.strip() not in os.environ:
            os.environ[_k.strip()] = _v.strip()

REDIS_HOST = os.environ.get("VPS_REDIS_HOST", "127.0.0.1")
REDIS_PORT = int(os.environ.get("VPS_REDIS_PORT", "6380"))

# Minimum seconds between gate invocations (avoid hammering on burst signals)
MIN_INTERVAL_S = 60
_last_run: float = 0.0


def _run_gate() -> None:
    global _last_run
    now = time.monotonic()
    if now - _last_run < MIN_INTERVAL_S:
        log.info("Gate already ran recently — skipping duplicate signal")
        return
    _last_run = now
    log.info("Firing Claude Code gate: claude --print @skill_gate_discoveries.md")
    try:
        result = subprocess.run(
            [CLAUDE, "--print", "--no-confirmation",
             "-p", f"@{SKILL}"],
            capture_output=True, text=True, timeout=600,
        )
        if result.returncode == 0:
            log.info("Gate completed OK")
        else:
            log.warning("Gate exited %d: %s", result.returncode,
                        result.stderr[:200] if result.stderr else "")
    except subprocess.TimeoutExpired:
        log.warning("Gate timed out after 600s")
    except Exception as e:
        log.error("Gate launch failed: %s", e)


def main() -> None:
    log.info("raw_listener starting (redis=%s:%d)", REDIS_HOST, REDIS_PORT)

    while True:
        try:
            import redis
            rc = redis.Redis(host=REDIS_HOST, port=REDIS_PORT,
                             decode_responses=True, socket_timeout=5)
            rc.ping()
            log.info("Redis connected — subscribing to corvus:raw_ready")

            # Check the fallback queue first (in case we missed signals while down)
            pending = rc.llen("corvus:raw_ready_queue")
            if pending:
                log.info("Found %d queued signal(s) — running gate now", pending)
                rc.delete("corvus:raw_ready_queue")
                _run_gate()

            # Subscribe to live signals
            pubsub = rc.pubsub()
            pubsub.subscribe("corvus:raw_ready")
            log.info("Subscribed. Waiting for signals...")

            for msg in pubsub.listen():
                if msg["type"] == "message":
                    count = msg.get("data", "?")
                    log.info("Signal received: %s new raw discoveries", count)
                    # Drain the fallback queue too
                    rc.delete("corvus:raw_ready_queue")
                    _run_gate()

        except KeyboardInterrupt:
            log.info("Shutting down")
            return
        except Exception as e:
            log.warning("Redis error: %s — reconnecting in 30s", e)
            time.sleep(30)


if __name__ == "__main__":
    main()
