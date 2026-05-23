import sys
import os
import json
import urllib.request
import urllib.parse
import urllib.error

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from _minmcp import MinMCP

BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "")
ADMIN_IDS = [int(x) for x in os.environ.get("TELEGRAM_ADMIN_IDS", "7994812711,238501003").split(",") if x.strip()]

mcp = MinMCP("telegram_mcp")


def _send(chat_id: int, text: str) -> dict:
    if not BOT_TOKEN:
        return {"error": "TELEGRAM_BOT_TOKEN not set"}
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
    body = json.dumps({"chat_id": chat_id, "text": text[:4096]}).encode()
    req = urllib.request.Request(url, data=body, headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            return json.loads(resp.read().decode())
    except urllib.error.HTTPError as e:
        return {"error": f"HTTP {e.code}: {e.read().decode()}"}
    except Exception as e:
        return {"error": str(e)}


@mcp.tool()
def notify(text: str, chat_id: int = 0) -> dict:
    """Send a plain text notification. If chat_id=0, sends to all admin chat IDs."""
    targets = [chat_id] if chat_id else ADMIN_IDS
    results = []
    for cid in targets:
        results.append(_send(cid, text))
    ok = all("error" not in r for r in results)
    return {"ok": ok, "sent_to": targets, "results": results}


if __name__ == "__main__":
    mcp.run()
