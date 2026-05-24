"""
captcha_detector.py — PostToolUse hook for screenshot and gemini image analysis.
Scans tool response text for captcha / block page signals.
Sends a Telegram alert and injects a SYSTEM REMINDER if detected.
"""
import json
import sys
import urllib.request

CAPTCHA_SIGNALS = [
    "verify you are human", "verify you're human",
    "i am not a robot", "i'm not a robot",
    "press and hold", "press & hold",
    "captcha", "recaptcha", "hcaptcha", "funcaptcha",
    "access denied", "403 forbidden",
    "cloudflare", "just a moment...",
    "security check", "ddos protection",
    "too many requests", "rate limit",
    "your connection has been blocked",
    "unusual traffic", "automated queries",
]


def _telegram(text: str) -> None:
    try:
        payload = json.dumps({
            "jsonrpc": "2.0", "id": 1, "method": "tools/call",
            "params": {"name": "notify", "arguments": {"text": text}}
        }).encode()
        req = urllib.request.Request(
            "http://localhost:8706/mcp", data=payload,
            headers={"Content-Type": "application/json"}
        )
        urllib.request.urlopen(req, timeout=5)
    except Exception:
        pass


def _text_from_response(resp: dict) -> str:
    for key in ("text", "content", "result", "analysis", "description", "output", "message"):
        val = resp.get(key, "")
        if isinstance(val, str) and val:
            return val.lower()
        if isinstance(val, list):
            return " ".join(str(v) for v in val).lower()
    return str(resp).lower()


def main():
    try:
        ctx = json.loads(sys.stdin.read() or "{}")
    except Exception:
        sys.exit(0)

    resp = ctx.get("tool_response", {})
    if not isinstance(resp, dict):
        sys.exit(0)

    text    = _text_from_response(resp)
    matched = next((s for s in CAPTCHA_SIGNALS if s in text), None)
    if not matched:
        sys.exit(0)

    _telegram(f"CAPTCHA/BLOCK detected during session: '{matched}'")

    print(json.dumps({
        "type": "system",
        "content": (
            f"SYSTEM REMINDER: CAPTCHA or block page detected — signal: '{matched}'.\n"
            "STOP all automation immediately.\n"
            "Required steps:\n"
            "1. mcp__capture__screenshot() — confirm current state\n"
            "2. mcp__telegram__send_screenshot() — send to admin\n"
            "3. AskUserQuestion: [🔄 Retry after manual solve] [⏭ Skip this job] [🚫 Abort]\n"
            "Do NOT attempt to auto-solve CAPTCHAs."
        )
    }))
    sys.exit(0)


if __name__ == "__main__":
    main()
