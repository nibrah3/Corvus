"""Send a school PDF report to Telegram."""
from __future__ import annotations

import logging
import os

import requests

log = logging.getLogger(__name__)

_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "")
_ADMIN_IDS = [
    cid.strip()
    for cid in os.environ.get("TELEGRAM_ADMIN_CHAT_ID", "").replace(";", ",").split(",")
    if cid.strip()
]

_CRITERIA_EMOJI = {
    "community_college":      "🏫",
    "no_id_verification":     "🪪",
    "no_transcript_required": "📄",
    "monthly_enrollment":     "📅",
    "instant_acceptance":     "⚡",
    "monthly_refund":         "💸",
}


def _caption(school: dict) -> str:
    name  = school.get("name", "Unknown")
    score = school.get("criteria_score", 0)
    url   = school.get("url", "")

    met = [
        f"{_CRITERIA_EMOJI.get(c, '•')} {c.replace('_', ' ').title()}"
        for c in (school.get("filters") or [])
    ]

    lines = [
        f"*{name}*",
        f"Score: {score}/6 criteria",
        "",
    ]
    if met:
        lines.append("*Criteria met:*")
        lines.extend(met)
    if url:
        lines.append(f"\n🔗 {url}")

    return "\n".join(lines)


def send_school_pdf(school: dict, pdf_bytes: bytes) -> bool:
    """Send the school PDF to all admin chat IDs. Returns True if at least one succeeded."""
    if not _BOT_TOKEN:
        log.warning("TELEGRAM_BOT_TOKEN not set — skipping notify")
        return False
    if not _ADMIN_IDS:
        log.warning("TELEGRAM_ADMIN_CHAT_ID not set — skipping notify")
        return False

    name    = school.get("name", "school").replace(" ", "_")[:40]
    caption = _caption(school)
    ok      = False

    for chat_id in _ADMIN_IDS:
        try:
            r = requests.post(
                f"https://api.telegram.org/bot{_BOT_TOKEN}/sendDocument",
                data={"chat_id": chat_id, "caption": caption, "parse_mode": "Markdown"},
                files={"document": (f"{name}_school_report.pdf", pdf_bytes, "application/pdf")},
                timeout=30,
            )
            if r.ok:
                log.info("PDF sent to chat %s: %s", chat_id, name)
                ok = True
            else:
                log.warning("Telegram sendDocument failed (chat %s): %s", chat_id, r.text[:200])
        except Exception as e:
            log.warning("Telegram send error (chat %s): %s", chat_id, e)

    return ok


def notify_text(text: str) -> None:
    """Send a plain text status message to all admin chats."""
    if not _BOT_TOKEN or not _ADMIN_IDS:
        return
    for chat_id in _ADMIN_IDS:
        try:
            requests.post(
                f"https://api.telegram.org/bot{_BOT_TOKEN}/sendMessage",
                json={"chat_id": chat_id, "text": text, "parse_mode": "Markdown"},
                timeout=10,
            )
        except Exception:
            pass
