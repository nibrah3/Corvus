#!/usr/bin/env python3
"""
corvus_imap_monitor.py — Multi-account IMAP verification code watcher.

Loads all profiles from Postgres that have imap_password set.
Opens one persistent IMAP connection per unique email account.
Watches for verification emails and stores extracted codes in Redis.

Redis key: corvus:verify:{email_address}  → {"code": "XXXXXXXX", "from": "...", "ts": ...}
TTL: 10 minutes (codes expire after that)

Browser-use picks up the code via the /verify-code endpoint or Redis directly.

Run as a daemon:  python3 corvus_imap_monitor.py
Systemd service:  corvus-imap-monitor.service
"""
import imaplib
import email
import email.header
import json
import logging
import os
import re
import socket
import sys
import threading
import time
from datetime import datetime

import psycopg2
import psycopg2.extras

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [imap] %(message)s",
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler("/opt/corvus/logs/imap_monitor.log", mode="a"),
    ],
)
log = logging.getLogger("imap")

PG_DSN    = os.getenv("DATABASE_URL", "postgresql://corvus:corvus-local-password@localhost:5432/careerbridge")
REDIS_URL = os.getenv("REDIS_URL", "redis://localhost:6379")
CODE_TTL  = 600  # 10 minutes

# Patterns that extract a verification code from email body text
CODE_PATTERNS = [
    r'\b([A-Z0-9]{6,10})\b',              # Generic 6-10 char alphanumeric
    r'(?:code|token|pin)[:\s]+([0-9]{4,8})',  # "code: 12345"
    r'(?:verify|verification)[:\s]+([A-Z0-9]{4,10})',
    r'\b([0-9]{6})\b',                    # 6-digit OTP
    r'\b([0-9]{8})\b',                    # 8-digit code (Greenhouse)
]

VERIFICATION_SENDERS = [
    "greenhouse.io", "lever.co", "dataannotation.tech",
    "prolific.com", "scale.com", "scaleai.com",
    "toloka.ai", "upwork.com", "no-reply", "noreply",
    "verify", "confirm", "account",
]


class RedisClient:
    def __init__(self, url: str):
        import urllib.parse
        p = urllib.parse.urlparse(url)
        self.host = p.hostname or "127.0.0.1"
        self.port = p.port or 6379

    def _cmd(self, *parts):
        with socket.create_connection((self.host, self.port), timeout=5) as s:
            cmd = f"*{len(parts)}\r\n" + "".join(f"${len(str(p))}\r\n{p}\r\n" for p in parts)
            s.sendall(cmd.encode())
            return s.recv(4096).decode(errors="replace")

    def setex(self, key: str, ttl: int, value: str):
        try:
            self._cmd("SETEX", key, str(ttl), value)
        except Exception as e:
            log.warning(f"Redis SETEX failed: {e}")

    def get(self, key: str) -> str | None:
        try:
            reply = self._cmd("GET", key)
            if reply.startswith("$-1"):
                return None
            lines = reply.split("\r\n")
            return lines[1] if len(lines) > 1 else None
        except Exception:
            return None


redis = RedisClient(REDIS_URL)


def load_profiles() -> list[dict]:
    """Load all profiles with imap credentials from Postgres."""
    try:
        conn = psycopg2.connect(PG_DSN)
        cur  = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
        cur.execute("""
            SELECT id, name, email, imap_password,
                   COALESCE(imap_server, 'imap.gmail.com') AS imap_server,
                   COALESCE(imap_port, 993) AS imap_port
            FROM profiles
            WHERE imap_password IS NOT NULL AND imap_password != ''
        """)
        profiles = [dict(r) for r in cur.fetchall()]
        conn.close()
        log.info(f"Loaded {len(profiles)} profiles with IMAP credentials")
        return profiles
    except Exception as e:
        log.error(f"Failed to load profiles: {e}")
        return []


def is_verification_email(msg) -> bool:
    """Return True if this email looks like a verification/code email."""
    sender = str(msg.get("From", "")).lower()
    subject = str(msg.get("Subject", "")).lower()
    check = sender + " " + subject
    return any(kw in check for kw in VERIFICATION_SENDERS + [
        "verification", "verify", "confirm", "code", "token", "activate"
    ])


def decode_header(value: str) -> str:
    parts = email.header.decode_header(value)
    decoded = []
    for part, charset in parts:
        if isinstance(part, bytes):
            decoded.append(part.decode(charset or "utf-8", errors="replace"))
        else:
            decoded.append(str(part))
    return " ".join(decoded)


def extract_code(body: str) -> str | None:
    """Extract the most likely verification code from email body."""
    for pattern in CODE_PATTERNS:
        m = re.search(pattern, body, re.IGNORECASE)
        if m:
            code = m.group(1)
            # Filter out common false positives (years, very long strings)
            if len(code) < 4 or len(code) > 12:
                continue
            if code.isdigit() and int(code) > 1900 and int(code) < 2100 and len(code) == 4:
                continue  # Skip years
            return code
    return None


def get_body(msg) -> str:
    """Extract plain text body from email message."""
    body = ""
    if msg.is_multipart():
        for part in msg.walk():
            ctype = part.get_content_type()
            if ctype == "text/plain":
                payload = part.get_payload(decode=True)
                if payload:
                    body += payload.decode("utf-8", errors="replace") + "\n"
    else:
        payload = msg.get_payload(decode=True)
        if payload:
            body = payload.decode("utf-8", errors="replace")
    return body


def process_new_emails(imap: imaplib.IMAP4_SSL, profile: dict):
    """Check UNSEEN emails and extract + store verification codes."""
    try:
        imap.select("INBOX")
        _, data = imap.search(None, "UNSEEN")
        msg_ids = data[0].split()
        if not msg_ids:
            return

        log.info(f"[{profile['email']}] {len(msg_ids)} unseen messages")
        for mid in msg_ids[-10:]:  # Process last 10 max
            _, raw = imap.fetch(mid, "(RFC822)")
            if not raw or not raw[0]:
                continue
            msg = email.message_from_bytes(raw[0][1])

            if not is_verification_email(msg):
                continue

            sender = str(msg.get("From", ""))
            subject = decode_header(str(msg.get("Subject", "")))
            body    = get_body(msg)
            code    = extract_code(body)

            if code:
                redis_key = f"corvus:verify:{profile['email']}"
                payload   = json.dumps({
                    "code": code, "from": sender,
                    "subject": subject, "ts": datetime.utcnow().isoformat(),
                    "profile_id": profile["id"],
                })
                redis.setex(redis_key, CODE_TTL, payload)
                log.info(f"[{profile['email']}] Code stored: {code} (from: {sender[:50]})")
            else:
                log.debug(f"[{profile['email']}] Verification email but no code found: {subject}")

    except Exception as e:
        log.warning(f"[{profile['email']}] process_new_emails error: {e}")


def watch_account(profile: dict):
    """Persistent watcher thread for one email account."""
    email_addr = profile["email"]
    server     = profile["imap_server"]
    port       = int(profile["imap_port"])
    password   = profile["imap_password"]

    log.info(f"Starting watcher: {email_addr} @ {server}:{port}")

    while True:
        try:
            imap = imaplib.IMAP4_SSL(server, port)
            imap.login(email_addr, password)
            log.info(f"[{email_addr}] Connected")

            # Initial scan of recent unread
            process_new_emails(imap, profile)

            # Poll every 30 seconds (IDLE would be better but needs keepalive complexity)
            while True:
                time.sleep(30)
                try:
                    imap.noop()  # Keep connection alive
                    process_new_emails(imap, profile)
                except imaplib.IMAP4.abort:
                    log.warning(f"[{email_addr}] Connection aborted, reconnecting...")
                    break
                except Exception as e:
                    log.warning(f"[{email_addr}] Poll error: {e}")
                    break

            try:
                imap.logout()
            except Exception:
                pass

        except imaplib.IMAP4.error as e:
            log.error(f"[{email_addr}] IMAP auth/connect error: {e}")
            time.sleep(120)  # Back off 2 min on auth errors
        except Exception as e:
            log.error(f"[{email_addr}] Unexpected error: {e}")
            time.sleep(30)


def main():
    log.info("corvus_imap_monitor starting...")
    profiles = load_profiles()

    if not profiles:
        log.warning("No profiles with IMAP credentials found. Polling every 5 min for new profiles.")
        while True:
            time.sleep(300)
            profiles = load_profiles()
            if profiles:
                break

    threads = []
    for profile in profiles:
        t = threading.Thread(
            target=watch_account,
            args=(profile,),
            name=f"imap-{profile['email']}",
            daemon=True,
        )
        t.start()
        threads.append(t)
        log.info(f"Watcher thread started: {profile['email']}")

    # Reload profiles every hour to pick up new ones
    while True:
        time.sleep(3600)
        new_profiles = load_profiles()
        current_emails = {p["email"] for p in profiles}
        for p in new_profiles:
            if p["email"] not in current_emails:
                log.info(f"New profile detected: {p['email']} — starting watcher")
                t = threading.Thread(
                    target=watch_account, args=(p,),
                    name=f"imap-{p['email']}", daemon=True,
                )
                t.start()
                threads.append(t)
        profiles = new_profiles


if __name__ == "__main__":
    main()
