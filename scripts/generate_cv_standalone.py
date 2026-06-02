"""
generate_cv_standalone.py — Menu-triggered CV / cover letter generator.

Usage:
  python generate_cv_standalone.py --profile <profile_id> --job-url <url>
  python generate_cv_standalone.py --profile <profile_id> --job-url <url> --cover-letter

Fetches the profile from vps_mcp (localhost:8713), scrapes the job page,
then calls cv_generator to produce a tailored CV (and optionally a cover letter).
Prints a JSON result dict for Claude to read.
"""
import argparse
import json
import sys
import re
import urllib.request
from pathlib import Path

CB_DIR  = Path(__file__).resolve().parent.parent
CV_DIR  = CB_DIR / "cvs"
VPS_URL = "http://localhost:8713/mcp"

sys.path.insert(0, str(CB_DIR))


# ── VPS profile fetch ──────────────────────────────────────────────────────────

_seq = 0

def _mcp_call(tool: str, **kwargs) -> dict:
    global _seq
    _seq += 1
    body = json.dumps({
        "jsonrpc": "2.0", "id": _seq,
        "method": "tools/call",
        "params": {"name": tool, "arguments": kwargs},
    }).encode()
    req = urllib.request.Request(
        VPS_URL, data=body, headers={"Content-Type": "application/json"}
    )
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            resp = json.loads(r.read())
        content = resp["result"]["content"][0]["text"]
        return json.loads(content)
    except Exception as e:
        return {"error": str(e)}


# ── Job page scraper ───────────────────────────────────────────────────────────

def _scrape_job(url: str) -> dict:
    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/124.0.0.0 Safari/537.36"
        )
    }
    req = urllib.request.Request(url, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=20) as r:
            html = r.read().decode("utf-8", errors="replace")
    except Exception as e:
        return {"error": f"Could not fetch job page: {e}"}

    # Extract title
    title_match = re.search(r"<title[^>]*>([^<]+)</title>", html, re.I)
    title = title_match.group(1).strip() if title_match else "Job Opportunity"
    title = re.sub(r"\s*[|\-–]\s*.+$", "", title).strip()  # strip site name suffix

    # Extract company from og:site_name or title suffix
    company_match = re.search(
        r'(?:og:site_name|name=["\']company["\'])[^>]+content=["\']([^"\']+)["\']',
        html, re.I
    )
    company = company_match.group(1).strip() if company_match else "the company"

    # Strip HTML → plain text for description
    text = re.sub(r"<script[^>]*>[\s\S]*?</script>", " ", html, flags=re.I)
    text = re.sub(r"<style[^>]*>[\s\S]*?</style>", " ", text, flags=re.I)
    text = re.sub(r"<[^>]+>", " ", text)
    text = re.sub(r"&[a-z]+;", " ", text)
    text = re.sub(r"\s+", " ", text).strip()

    # Keep a generous chunk — cv_generator does its own keyword extraction
    description = text[:8000]

    job_id = re.sub(r"[^a-z0-9]", "_", url.lower())[-40:]

    return {
        "id":          job_id,
        "title":       title,
        "company":     company,
        "description": description,
        "url":         url,
    }


# ── Main ───────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--profile",       required=True, help="Profile ID")
    parser.add_argument("--job-url",       required=True, help="Job posting URL")
    parser.add_argument("--cover-letter",  action="store_true", help="Also generate cover letter")
    args = parser.parse_args()

    result = {}

    # 1. Fetch profile from VPS
    profile = _mcp_call("get_profile", profile_id=args.profile)
    if "error" in profile:
        result["error"] = f"Profile not found: {profile['error']}"
        print(json.dumps(result))
        sys.exit(1)

    # 2. Scrape job page
    job = _scrape_job(args.job_url)
    if "error" in job:
        result["error"] = job["error"]
        print(json.dumps(result))
        sys.exit(1)

    CV_DIR.mkdir(parents=True, exist_ok=True)

    # 3. Generate CV
    try:
        from cv_generator import generate_cv, generate_cover_letter
        cv = generate_cv(profile, job, out_dir=str(CV_DIR))
        result["cv"] = {
            "score":    cv["score"],
            "matched":  cv["matched"][:8],
            "missing":  cv["missing"][:5],
            "txt_path": cv["txt_path"],
            "pdf_path": cv["pdf_path"],
        }
    except Exception as e:
        result["error"] = f"CV generation failed: {e}"
        print(json.dumps(result))
        sys.exit(1)

    # 4. Optionally generate cover letter
    if args.cover_letter:
        try:
            cl = generate_cover_letter(profile, job, out_dir=str(CV_DIR))
            result["cover_letter"] = {
                "txt_path": cl["txt_path"],
                "persona_applied": cl.get("persona_applied", False),
            }
        except Exception as e:
            result["cover_letter"] = {"error": str(e)}

    result["job_title"]   = job["title"]
    result["company"]     = job["company"]
    result["profile_id"]  = args.profile

    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
