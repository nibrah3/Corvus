import sys
import os
import json
import urllib.request
import urllib.parse
import urllib.error

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from _minmcp import MinMCP

CRAWLEE_BASE = os.environ.get("CRAWLEE_API", "http://localhost:3100")
FIRECRAWL_BASE = os.environ.get("FIRECRAWL_API", "http://localhost:7788")

mcp = MinMCP("crawlee_mcp")


def _post(url: str, body: dict) -> dict:
    data = json.dumps(body).encode()
    req = urllib.request.Request(
        url, data=data,
        headers={"Content-Type": "application/json"},
        method="POST"
    )
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            return json.loads(resp.read().decode())
    except urllib.error.HTTPError as e:
        return {"error": f"HTTP {e.code}: {e.reason}", "url": url}
    except Exception as e:
        return {"error": str(e), "url": url}


def _get(url: str) -> dict:
    try:
        with urllib.request.urlopen(url, timeout=15) as resp:
            return json.loads(resp.read().decode())
    except Exception as e:
        return {"error": str(e), "url": url}


@mcp.tool()
def trigger_scrape(source: str, keywords: str = "", limit: int = 50) -> dict:
    """Trigger a Crawlee scrape job for a source (reddit, hackernews, wellfound, ycombinator, etc.)."""
    body = {"keywords": keywords, "limit": limit}
    return _post(f"{CRAWLEE_BASE}/scrape/{source}", body)


@mcp.tool()
def scrape_url(url: str) -> dict:
    """Extract job description text from a URL via Firecrawl."""
    body = {"url": url, "formats": ["markdown"]}
    result = _post(f"{FIRECRAWL_BASE}/v1/scrape", body)
    if "error" in result:
        return result
    content = result.get("data", {}).get("markdown", "")
    return {"url": url, "content": content[:8000], "truncated": len(content) > 8000}


@mcp.tool()
def get_queue_stats() -> dict:
    """Get current queue statistics from the Crawlee API."""
    return _get(f"{CRAWLEE_BASE}/queue/stats")


if __name__ == "__main__":
    mcp.run()
