"""
filter_upsert_job.py — PreToolUse hook for mcp__vps__upsert_job.
Blocks jobs from social media domains before they enter the database.
Exit code 2 = blocked; Claude Code surfaces the error message.
"""
import json
import sys

BLOCKED_DOMAINS = {
    "facebook.com", "fb.com", "instagram.com", "twitter.com",
    "x.com", "tiktok.com", "snapchat.com", "linkedin.com",
    "youtube.com", "pinterest.com",
}


def main():
    try:
        ctx = json.loads(sys.stdin.read() or "{}")
    except Exception:
        sys.exit(0)

    url = (ctx.get("tool_input", {}).get("url") or "").lower()
    if not url:
        sys.exit(0)

    for domain in BLOCKED_DOMAINS:
        if domain in url:
            print(json.dumps({
                "type": "error",
                "content": (
                    f"BLOCKED: job URL '{url[:80]}' is from {domain} (social media). "
                    "Only direct career pages, Reddit, and Quora-type sources are allowed. "
                    "Do not save this job."
                )
            }))
            sys.exit(2)

    sys.exit(0)


if __name__ == "__main__":
    main()
