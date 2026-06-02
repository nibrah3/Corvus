"""
hum_type_chunked.py — Chunked humanized typing via MCP HTTP.

Use this when Claude Code is driving the browser directly via MCPs and needs
to type a prose answer longer than ~220 characters without hitting the MCP
tool timeout.

Usage (from Python):
    from scripts.hum_type_chunked import type_chunked_via_mcp
    type_chunked_via_mcp("Long prose answer here...", profile_seed=42)

The function splits text at sentence boundaries, sends each chunk to the
humanizer_mcp HTTP server individually, and adds natural inter-sentence pauses.
"""
from __future__ import annotations

import json
import re
import time
import urllib.request

MCP_URL    = "http://localhost:8701/mcp"
CHUNK_CHARS = 220   # max chars per MCP call


def _mcp_call(tool: str, arguments: dict) -> dict:
    body = json.dumps({
        "jsonrpc": "2.0",
        "id": 1,
        "method": "tools/call",
        "params": {"name": tool, "arguments": arguments},
    }).encode()
    req = urllib.request.Request(
        MCP_URL, data=body, headers={"Content-Type": "application/json"}
    )
    with urllib.request.urlopen(req, timeout=90) as r:
        return json.loads(r.read())


def type_chunked_via_mcp(
    text: str,
    profile_seed: int = 42,
    pause_between: float = 0.6,
) -> list[str]:
    """
    Type text via humanizer_mcp, splitting at sentence boundaries.

    Args:
        text:           Full text to type.
        profile_seed:   Pass same seed as other humanizer calls in the session.
        pause_between:  Seconds to sleep between sentence chunks (simulates
                        natural reading/thinking pause).

    Returns:
        List of chunk strings that were typed.
    """
    if not text:
        return []

    parts  = re.split(r'(?<=[.!?])\s+', text.strip())
    chunks: list[str] = []
    chunk  = ""

    for part in parts:
        candidate = (chunk + " " + part).strip() if chunk else part
        if len(candidate) <= CHUNK_CHARS:
            chunk = candidate
        else:
            if chunk:
                chunks.append(chunk)
            chunk = part

    if chunk:
        chunks.append(chunk)

    for i, c in enumerate(chunks):
        _mcp_call("humanized_type", {"text": c, "profile_seed": profile_seed})
        if i < len(chunks) - 1:
            time.sleep(pause_between)

    return chunks


if __name__ == "__main__":
    import sys
    text = sys.argv[1] if len(sys.argv) > 1 else "Hello world. This is a test sentence. It should be typed in chunks."
    print(f"Typing {len(text)} chars in chunks...")
    chunks = type_chunked_via_mcp(text)
    print(f"Done — {len(chunks)} chunk(s): {[len(c) for c in chunks]}")
