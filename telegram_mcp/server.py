"""
Telegram MCP server — outbound status and streaming only.

Tools:
  notify          Send a plain message to admin
  stream_update   Send a live progress tick during a long task
  send_screenshot Send an image to admin
  broadcast       Send to all admin chat IDs

Approval flows removed — Claude Code Remote Control handles all interactive decisions.
"""
from __future__ import annotations

from typing import Optional
from _minmcp import MinMCP

mcp = MinMCP("telegram")


@mcp.tool()
def notify(text: str, chat_id: Optional[int] = None) -> dict:
    """
    Send a status message to the admin Telegram chat.

    Use for task start, completion, and error alerts.
    Supports HTML: <b>bold</b> <i>italic</i> <code>code</code>

    Args:
        text:    Message text.
        chat_id: Target chat (defaults to TELEGRAM_ADMIN_CHAT_ID).

    Returns:
        {ok: bool, message_id: int}
    """
    try:
        from telegram_mcp._bot import send_message, admin_chat_ids
        cid = chat_id or admin_chat_ids()[0]
        r = send_message(cid, text)
        if r.get("ok"):
            return {"ok": True, "message_id": r["result"]["message_id"]}
        return {"ok": False, "error": r.get("description", "unknown")}
    except Exception as exc:
        return {"ok": False, "error": str(exc)}


@mcp.tool()
def stream_update(
    step: str,
    message: str,
    chat_id: Optional[int] = None,
) -> dict:
    """
    Send a live progress update during a long-running task.

    Call this at meaningful checkpoints so the user can see progress
    and detect if the task is stuck.

    Args:
        step:    Short label for the current step (e.g. "3/10", "uploading", "done").
        message: Plain description of what just happened.
        chat_id: Target chat (defaults to TELEGRAM_ADMIN_CHAT_ID).

    Returns:
        {ok: bool}
    """
    try:
        from telegram_mcp._bot import send_message, admin_chat_ids
        cid = chat_id or admin_chat_ids()[0]
        text = f"[{step}] {message}"
        r = send_message(cid, text, parse_mode="")
        return {"ok": r.get("ok", False)}
    except Exception as exc:
        return {"ok": False, "error": str(exc)}


@mcp.tool()
def send_screenshot(image_path: str, caption: str = "", chat_id: Optional[int] = None) -> dict:
    """
    Send a screenshot or image to the admin Telegram chat.

    Args:
        image_path: Full local path to PNG or JPEG.
        caption:    Optional caption below the image.
        chat_id:    Target chat (defaults to primary admin).

    Returns:
        {ok: bool, message_id: int}
    """
    try:
        from telegram_mcp._bot import send_photo, admin_chat_ids
        cid = chat_id or admin_chat_ids()[0]
        r = send_photo(cid, image_path, caption=caption)
        if r.get("ok"):
            return {"ok": True, "message_id": r["result"]["message_id"]}
        return {"ok": False, "error": r.get("description", "unknown")}
    except Exception as exc:
        return {"ok": False, "error": str(exc)}


@mcp.tool()
def broadcast(text: str) -> dict:
    """
    Send a message to ALL admin chat IDs simultaneously.

    Args:
        text: Message text (HTML OK).

    Returns:
        {sent: int, failed: int}
    """
    try:
        from telegram_mcp._bot import send_message, admin_chat_ids
        sent, failed = 0, 0
        for cid in admin_chat_ids():
            r = send_message(cid, text)
            if r.get("ok"):
                sent += 1
            else:
                failed += 1
        return {"sent": sent, "failed": failed}
    except Exception as exc:
        return {"sent": 0, "failed": 0, "error": str(exc)}


if __name__ == "__main__":
    mcp.run()
