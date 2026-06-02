"""
run_assessment.py — CLI entry point for AssessmentPipeline.

Called by Claude Code after job approval. Fetches job + profile from VPS,
resolves the IXBrowser CDP URL, then runs the pipeline in the requested mode.

Usage:
    python run_assessment.py --job-id 123 --profile <profile_id> --mode supervised
    python run_assessment.py --job-id 123 --profile <profile_id> --mode throughput
    python run_assessment.py --url https://... --profile <profile_id> --mode supervised
"""
import argparse
import json
import logging
import os
import sys
import urllib.request
from pathlib import Path

logging.basicConfig(
    level=logging.DEBUG,
    format="%(asctime)s %(levelname)s %(name)s %(message)s",
    stream=sys.stderr,
)

CB_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(CB_DIR))

VPS_URL = "http://localhost:8713/mcp"
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


def _tg_notify(text: str) -> None:
    """Send a one-line Telegram status message to all admin chats (non-fatal)."""
    import os as _os
    token = _os.environ.get("TELEGRAM_BOT_TOKEN", "")
    if not token:
        return
    ids: list[str] = []
    for key in ("TELEGRAM_ADMIN_CHAT_ID", "TELEGRAM_ADMIN_CHAT_ID_2"):
        for part in _os.environ.get(key, "").replace(";", ",").split(","):
            if part.strip() and part.strip() not in ids:
                ids.append(part.strip())
    import json as _json, urllib.request as _req
    for chat_id in ids:
        try:
            body = _json.dumps({"chat_id": chat_id, "text": text,
                                "parse_mode": "Markdown"}).encode()
            rq = _req.Request(
                f"https://api.telegram.org/bot{token}/sendMessage",
                data=body, headers={"Content-Type": "application/json"},
            )
            _req.urlopen(rq, timeout=6)
        except Exception:
            pass


def _read_defaults() -> dict:
    """Read D:\\cb-core\\.defaults.json; return {} on any error."""
    try:
        p = CB_DIR / ".defaults.json"
        return json.loads(p.read_text(encoding="utf-8")) if p.exists() else {}
    except Exception:
        return {}


def _get_cdp_url(profile: dict) -> str:
    """
    Resolve IXBrowser CDP WebSocket URL for the profile.

    Routing is driven by browser_mode in .defaults.json:
      "api"  → IXBrowser local API (paid) — closes existing session, opens fresh.
      "free" → psutil port scan using cdp_port from .defaults.json (default 9222).
      unset  → try API first, fall back to port scan (legacy auto-detect).
    """
    defaults      = _read_defaults()
    browser_mode  = defaults.get("browser_mode", "")        # "api" | "free" | ""
    cdp_port      = int(defaults.get("cdp_port", 9222))
    profile_name  = profile.get("name", "the candidate")
    profile_id    = profile.get("id") or profile.get("profile_id") or ""
    profile_email = profile.get("email", "")

    # ── Free mode (explicit) ──────────────────────────────────────────────────
    if browser_mode == "free":
        try:
            from careerbridge.ixbrowser_connector import _open_via_psutil
            _tg_notify(
                f"Connecting to open browser for *{profile_name}* "
                f"(free mode — port {cdp_port})."
            )
            return _open_via_psutil(port=cdp_port)
        except Exception as e:
            _tg_notify(f"⚠️ Could not find open browser for *{profile_name}*: {e}")
            return ""

    # ── API mode (explicit or auto-detect legacy) ─────────────────────────────
    try:
        # Fast path: use known IXBrowser profile mapping from defaults.json if it exists.
        # This avoids calling ensure_ixbrowser_profile which does a slow get_profile_list.
        ix_mapping_path = CB_DIR / "defaults.json"
        ix_mapping: dict = {}
        try:
            ix_mapping = json.loads(ix_mapping_path.read_text()).get("ixbrowser_profiles", {})
        except Exception:
            pass

        if profile_id and profile_id in ix_mapping:
            ix_id = int(ix_mapping[profile_id])
        else:
            from proxy_manager import ensure_ixbrowser_profile, location_to_country
            country = location_to_country(profile.get("location", ""))
            ix_id   = ensure_ixbrowser_profile(
                postgres_id=profile_id,
                full_name=profile.get("name", profile_id),
                country=country,
                proxy_type="socks5",
            )

        # Close any existing session cleanly before opening fresh
        try:
            from careerbridge.ixbrowser_connector import ix_close_profile
            ix_close_profile(ix_id)
            import time as _t; _t.sleep(1.5)
        except Exception:
            pass

        _tg_notify(
            f"Opening browser for *{profile_name}* "
            f"— previous session closed, starting fresh."
        )

        from careerbridge.ixbrowser_connector import ix_open_profile
        return ix_open_profile(ix_id)
    except Exception:
        pass

    # ── Legacy fallback: psutil scan on default port ──────────────────────────
    if browser_mode != "api":
        try:
            from careerbridge.ixbrowser_connector import _open_via_psutil
            return _open_via_psutil()
        except Exception:
            pass

    return ""


def main():
    parser = argparse.ArgumentParser(description="Run one assessment")
    parser.add_argument("--job-id",   type=int,  default=None,  help="VPS job ID")
    parser.add_argument("--url",      type=str,  default=None,  help="Direct assessment URL")
    parser.add_argument("--profile",  type=str,  required=True, help="Profile ID")
    parser.add_argument("--mode",     type=str,  default="supervised",
                        choices=["supervised", "throughput"],
                        help="supervised = humanized + gates | throughput = fast CDP")
    args = parser.parse_args()

    if not args.job_id and not args.url:
        print(json.dumps({"error": "Provide --job-id or --url"}))
        sys.exit(1)

    # 1. Fetch profile
    profile = _mcp_call("get_profile", profile_id=args.profile)
    if "error" in profile:
        print(json.dumps({"error": f"Profile not found: {profile['error']}"}))
        sys.exit(1)

    # 2. Resolve assessment URL
    url = args.url
    if not url and args.job_id:
        job = _mcp_call("get_job", job_id=args.job_id)
        if "error" in job:
            print(json.dumps({"error": f"Job not found: {job['error']}"}))
            sys.exit(1)
        url = job.get("url") or ""
        if not url:
            print(json.dumps({"error": f"Job {args.job_id} has no URL"}))
            sys.exit(1)

    # 3. Resolve CDP URL (IXBrowser WebSocket)
    cdp_url = _get_cdp_url(profile)

    # 4. Run pipeline
    from careerbridge.assessment_pipeline import AssessmentPipeline, AssessmentConfig

    cfg    = AssessmentConfig(
        cdp_url=cdp_url,
        url=url,
        profile=profile,
        mode=args.mode,
    )
    result = AssessmentPipeline(cfg).run()

    # 5. Update job status if job_id was given
    if args.job_id:
        status = "applied" if result.ok else "error"
        _mcp_call("update_job_status",
                  job_id=args.job_id,
                  status=status,
                  result=result.error or "")

    print(json.dumps({
        "ok":            result.ok,
        "pages_done":    result.pages_done,
        "llm_calls":     result.llm_calls,
        "actions_taken": result.actions_taken,
        "error":         result.error,
        "mode":          args.mode,
    }, indent=2))


if __name__ == "__main__":
    main()
