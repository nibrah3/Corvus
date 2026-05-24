"""Human-gate helpers for the assessment pipeline."""
from __future__ import annotations

import logging
import os
from typing import Optional

log = logging.getLogger(__name__)


def tg_notify(text: str) -> None:
    """Fire-and-forget Telegram notification. Silently ignores failures."""
    try:
        from telegram_mcp._bot import send_message, admin_chat_ids
        for cid in admin_chat_ids():
            send_message(cid, text)
    except Exception:
        pass


def claude_code_gate(label: str, draft: str, job_id=None,
                     timeout: float = 300.0) -> Optional[str]:
    """
    Primary gate: writes request to Redis → Claude Code hook picks it up →
    AskUserQuestion presented in Claude Code UI → answer written back to Redis.
    Returns the approved answer string, or None if the gate is unavailable.
    """
    try:
        from careerbridge.gate_client import request_gate
        tg_notify(
            f"📝 <b>Assessment gate</b> — <b>{label}</b>\n"
            f"<pre>{draft[:500]}</pre>\n"
            f"⏳ Waiting for your approval in Claude Code..."
        )
        return request_gate(
            field_label=label,
            draft=draft,
            job_id=job_id,
            timeout=timeout,
        )
    except Exception as e:
        log.warning("Claude Code gate failed (%s) — caller should fallback", e)
        return None
