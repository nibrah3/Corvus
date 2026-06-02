#!/usr/bin/env python3
"""
hook_trigger_discovery.py - PostToolUse hook (Module 6 quality gate)
Fires after mcp__vps__trigger_discovery.

What it does:
  1. Acknowledges the VPS discovery job has started
  2. Instructs Claude to launch the enrichment pipeline as a background Bash command
     so newly discovered jobs get official URLs and a PDF batch broadcast to all users
  3. Shows the Jobs sub-menu

The enrichment pipeline (enrich_jobs.py):
  - Finds all unenriched jobs in DB
  - Firecrawls platform URLs to extract official employer URLs
  - Firecrawls official URLs for authoritative job descriptions
  - Updates DB: official_url, official_description, enriched=True
  - On completion: generates batch PDF and broadcasts to all Telegram users
"""
import io
import json
import sys

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")


def main():
    try:
        raw = sys.stdin.buffer.read().decode("utf-8-sig", errors="replace")
        ctx = json.loads(raw) if raw.strip() else {}
    except Exception:
        sys.exit(0)

    tool_response = ctx.get("tool_response", {})
    if isinstance(tool_response, str):
        try:
            tool_response = json.loads(tool_response)
        except Exception:
            tool_response = {}
    if not isinstance(tool_response, dict):
        tool_response = {}

    if "error" in tool_response:
        print(
            "[DISCOVERY ERROR]\n"
            f"VPS discovery failed to start: {tool_response['error']}\n"
            "Tell the user: \"I had trouble kicking off the search - give me a moment.\"\n"
            "Then show the Jobs sub-menu."
        )
        sys.exit(0)

    source = ctx.get("tool_input", {}).get("source", "all")

    print(
        "[JOB DISCOVERY STARTED]\n"
        f"source={source}\n"
        "Tell the user: \"I've started searching for new job opportunities - "
        "I'll send the results straight to your phone when I'm done. "
        "This usually takes a few minutes.\"\n\n"
        "IMPORTANT - immediately after telling the user, run this Bash command "
        "(non-blocking background process):\n"
        "  C:\\Python314\\python.exe D:\\cb-core\\scripts\\enrich_jobs.py\n\n"
        "This enriches each discovered job with the employer's official URL, "
        "scrapes the authoritative job description, and broadcasts a PDF report "
        "to all registered users when complete.\n\n"
        "Then show the Jobs & Assessments sub-menu via AskUserQuestion.\n"
        "Do NOT poll for results — the PDF broadcast is the completion signal."
    )
    sys.exit(0)


if __name__ == "__main__":
    main()
