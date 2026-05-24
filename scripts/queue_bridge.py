"""
queue_bridge.py - Desktop application dispatcher.

Polls corvus:approved_jobs Redis queue. For each job:
  1. Fetches profile and job details from VPS postgres (via vps_mcp SSH tunnel)
  2. Generates a tailored CV locally (cv_generator.py + reportlab)
  3. Opens the candidate's IXBrowser profile via local API (port 53200)
  4. Runs browser-use LLM agent (3-LLM: workhorse + vision + reasoning) to fill the form
  5. Updates job status in VPS postgres

Requirements:
  - IXBrowser must be running and have profiles named to match postgres profile IDs
  - VPS SSH tunnels active (Redis:6380, Postgres:5433) -- run vps_tunnel.ps1
  - vps_mcp running on localhost:8713 -- run start_mcps.ps1
  - D:\\cb-core\\.env must contain OPENROUTER_API_KEY

Usage:
  python scripts/queue_bridge.py [--once]
  python scripts/queue_bridge.py --list-profiles
"""
from __future__ import annotations

import argparse
import asyncio
import json
import logging
import os
import socket
import sys
import time
import urllib.request
from pathlib import Path

CB_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(CB_DIR))

from careerbridge.ixbrowser_connector import (
    get_cdp_url,
    is_paid_account,
    ix_open_profile,
    ix_close_profile,
)
from careerbridge.application_pipeline import ApplicationPipeline, ApplicationConfig

# ── Config ──────────────────────────────────────────────────────────────────────

def _load_env():
    env_path = CB_DIR / ".env"
    if env_path.exists():
        for line in env_path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, _, v = line.partition("=")
                os.environ.setdefault(k.strip(), v.strip())

_load_env()

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger(__name__)

REDIS_HOST      = "127.0.0.1"
REDIS_PORT      = 6380  # SSH tunnel to VPS Redis
APPROVED_KEY    = "corvus:approved_jobs"
RESULTS_KEY     = "corvus:job_results"
POLL_INTERVAL   = 15

VPS_MCP_URL     = "http://localhost:8713/mcp"
IX_API_BASE     = "http://127.0.0.1:53200/api/v2"
CV_DIR          = CB_DIR / "cvs"

OPENROUTER_KEY      = os.environ.get("OPENROUTER_API_KEY", "")
OPENROUTER_BASE_URL = os.environ.get("OPENROUTER_BASE_URL", "https://openrouter.ai/api/v1")

# 3-LLM architecture (matches VPS browser-use container)
MODEL_WORKHORSE = os.environ.get("OPENROUTER_MODEL_WORKHORSE",
                                  os.environ.get("OPENROUTER_MODEL", "anthropic/claude-sonnet-4-6"))
MODEL_VISION    = os.environ.get("OPENROUTER_MODEL_VISION",    "openai/gpt-4o-mini")
MODEL_REASONING = os.environ.get("OPENROUTER_MODEL_REASONING", "openai/gpt-4o-mini")

TASK_TIMEOUT    = int(os.environ.get("TASK_TIMEOUT_SECONDS", "3600"))
MAX_STEPS       = int(os.environ.get("MAX_STEPS", "50"))

# ── Redis helpers ────────────────────────────────────────────────────────────────

def _redis_cmd(*parts: str) -> bytes:
    with socket.create_connection((REDIS_HOST, REDIS_PORT), timeout=5) as sock:
        cmd = f"*{len(parts)}\r\n" + "".join(f"${len(p)}\r\n{p}\r\n" for p in parts)
        sock.sendall(cmd.encode())
        data = b""
        while True:
            chunk = sock.recv(4096)
            if not chunk:
                break
            data += chunk
            if b"\r\n" in data:
                break
        return data


def _lpop(key: str) -> str | None:
    try:
        reply = _redis_cmd("LPOP", key).decode(errors="replace").strip()
        if reply in ("$-1", "*-1") or reply == "-1":
            return None
        lines = reply.split("\r\n")
        if lines[0].startswith("$") and len(lines) > 1:
            return lines[1]
        return None
    except Exception:
        return None


def _rpush(key: str, value: str) -> None:
    try:
        _redis_cmd("RPUSH", key, value)
    except Exception:
        pass


# ── VPS MCP helper ───────────────────────────────────────────────────────────────

_mcp_seq = 0


def _mcp_call(tool: str, **kwargs) -> dict:
    global _mcp_seq
    _mcp_seq += 1
    body = json.dumps({
        "jsonrpc": "2.0", "id": _mcp_seq,
        "method": "tools/call",
        "params": {"name": tool, "arguments": kwargs},
    }).encode()
    req = urllib.request.Request(VPS_MCP_URL, data=body,
                                  headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=45) as r:
            resp = json.loads(r.read())
        content = resp["result"]["content"][0]["text"]
        return json.loads(content)
    except Exception as e:
        return {"error": str(e)}


# ── CV generation (local) ────────────────────────────────────────────────────────

def _generate_cv(profile: dict, job: dict) -> dict | None:
    try:
        sys.path.insert(0, str(CB_DIR))
        from cv_generator import generate_cv
        CV_DIR.mkdir(parents=True, exist_ok=True)
        return generate_cv(profile, job, out_dir=str(CV_DIR))
    except Exception as e:
        logger.warning(f"CV generation failed: {e}")
        return None


# ── IXBrowser local API (port 53200) ─────────────────────────────────────────────

def ix_running() -> bool:
    try:
        with socket.create_connection(("127.0.0.1", 53200), timeout=2):
            return True
    except Exception:
        return False


def ix_list_profiles() -> list:
    from ixbrowser_local_api import IXBrowserClient
    client = IXBrowserClient()
    return client.get_profile_list(limit=100) or []


def ix_find_profile(postgres_profile_id: str) -> int:
    """Return IXBrowser profile_id (int) matching the postgres profile_id."""
    defaults_path = CB_DIR / "defaults.json"
    try:
        defaults = json.loads(defaults_path.read_text())
        mapping = defaults.get("ixbrowser_profiles", {})
        if postgres_profile_id in mapping:
            return int(mapping[postgres_profile_id])
    except Exception:
        pass

    from ixbrowser_local_api import IXBrowserClient
    client = IXBrowserClient()
    profiles = client.get_profile_list(keyword=postgres_profile_id, limit=5) or []
    for p in profiles:
        pid = p.get("profile_id") or p.get("id")
        if pid:
            return int(pid)

    raise RuntimeError(
        f"No IXBrowser profile found for '{postgres_profile_id}'. "
        f"Create an IXBrowser profile named '{postgres_profile_id}' "
        f"or add a mapping to D:\\cb-core\\defaults.json under 'ixbrowser_profiles'."
    )


def ix_create_profile(name: str, proxy_id: int | None = None) -> int:
    """Create a new IXBrowser profile and return its profile_id."""
    from ixbrowser_local_api import IXBrowserClient
    client = IXBrowserClient()
    kwargs = {"name": name, "site_url": "https://google.com"}
    if proxy_id:
        kwargs["proxy_id"] = proxy_id
    result = client.create_profile(**kwargs)
    if result is None:
        raise RuntimeError(f"IXBrowser create_profile failed: {client.message}")
    pid = result.get("profile_id") or result.get("id")
    if not pid:
        raise RuntimeError(f"No profile_id in create response: {result}")
    return int(pid)


# ── Dispatch ──────────────────────────────────────────────────────────────────────

def dispatch_job(job_payload: dict) -> dict:
    job_id     = job_payload.get("job_id")
    url        = job_payload.get("url", "")
    profile_id = job_payload.get("profile_id", "")
    company    = job_payload.get("company", "")
    title      = job_payload.get("title", "")

    if not url:
        return {"ok": False, "result": "no URL in payload"}

    # Fetch full job details
    job_raw = _mcp_call("get_job", job_id=job_id)
    if "error" in job_raw:
        return {"ok": False, "result": f"Job fetch failed: {job_raw['error']}"}
    profile_id = profile_id or job_raw.get("profile_id") or ""
    company    = company    or job_raw.get("company", "")
    title      = title      or job_raw.get("title", "")

    if not profile_id:
        return {"ok": False, "result": f"Job {job_id} has no profile_id set."}

    # Fetch candidate profile
    profile_raw = _mcp_call("get_profile", profile_id=profile_id)
    if "error" in profile_raw:
        return {"ok": False, "result": f"Profile fetch failed: {profile_raw['error']}"}

    # Generate tailored CV locally
    cv_pdf_path = None
    cv_result   = _generate_cv(profile_raw, job_raw)
    if cv_result:
        cv_pdf_path = cv_result.get("pdf_path")
        score       = cv_result.get("score", 0)
        logger.info(f"CV score={score}%  pdf={cv_pdf_path}")

    # ── IXBrowser CDP acquisition (paid = API, free = psutil scan) ─────────────
    profile_email    = profile_raw.get("email", "")
    profile_location = profile_raw.get("location", "")
    ix_id = None

    try:
        from proxy_manager import location_to_country
        country = location_to_country(profile_location)
    except Exception:
        country = "?"

    if is_paid_account(profile_email):
        # Paid: IXBrowser API must be up; resolve and open the profile
        if not ix_running():
            return {
                "ok": False,
                "result": (
                    f"IXBrowser is not running on {socket.gethostname()}. "
                    "Open IXBrowser then retry."
                ),
            }
        try:
            from proxy_manager import ensure_ixbrowser_profile
            ix_id = ensure_ixbrowser_profile(
                postgres_id=profile_id,
                full_name=profile_raw.get("name", profile_id),
                country=country,
                proxy_type="socks5",
            )
        except Exception:
            try:
                ix_id = ix_find_profile(profile_id)
            except RuntimeError as e:
                return {"ok": False, "result": str(e)}
        logger.info(f"Opening IXBrowser profile {ix_id} for '{profile_id}' (country={country})")
    else:
        # Free: user already has the profile open with --remote-debugging-port=9222
        logger.info(f"Free account — attaching to running IXBrowser for '{profile_id}'")

    try:
        cdp_url = get_cdp_url(profile_email, ix_profile_id=ix_id)
        logger.info(f"CDP ready: {cdp_url[:70]}")
    except Exception as e:
        return {"ok": False, "result": str(e)}

    # ── MANDATORY: Location verification ─────────────────────────────────────
    import time as _time
    _time.sleep(3)   # let browser fully initialise before IP check
    try:
        from ip_verifier import verify_location, print_location_banner
        ip_result = verify_location(cdp_url, country)
        print_location_banner(ip_result, profile_raw.get("name", profile_id), profile_location)
        if not ip_result["match"]:
            logger.warning(
                f"Location mismatch: expected {country.upper()}, "
                f"got {ip_result['country'].upper()} ({ip_result['ip']}). "
                "Proceeding — may be geo-blocked."
            )
    except Exception as e:
        logger.warning(f"IP verification failed (non-fatal): {e}")
    # ─────────────────────────────────────────────────────────────────────────

    # Run via ApplicationPipeline (owns task construction, LLM calls, popup handling)
    cfg = ApplicationConfig(
        cdp_url=cdp_url,
        url=url,
        profile=profile_raw,
        cv_path=cv_pdf_path,
        task_type=job_raw.get("task_type", "application"),
        max_steps=MAX_STEPS,
        timeout_s=TASK_TIMEOUT,
        job_id=job_id,
    )
    try:
        app_result = asyncio.run(ApplicationPipeline(cfg).run())
        result = {
            "ok": app_result.ok,
            "result": app_result.summary or app_result.error or "completed",
            "failure_type": app_result.failure_type,
        }
    except Exception as e:
        result = {"ok": False, "result": str(e), "failure_type": "unknown"}
    finally:
        if ix_id is not None:
            ix_close_profile(ix_id)

    return result


# ── Main loop ─────────────────────────────────────────────────────────────────────

def list_ix_profiles():
    hostname = socket.gethostname()
    if not ix_running():
        print(f"[{hostname}] IXBrowser not running - open IXBrowser and try again.")
        return
    profiles = ix_list_profiles()
    if not profiles:
        print("No IXBrowser profiles found.")
        return
    print(f"[{hostname}] {len(profiles)} IXBrowser profile(s):")
    for p in profiles:
        pid  = p.get("profile_id") or p.get("id", "?")
        name = p.get("name", "?")
        print(f"  IXBrowser profile_id={pid!r}  name={name!r}")
    print(
        "\nMap to postgres profile IDs in D:\\cb-core\\defaults.json:\n"
        '  { "ixbrowser_profiles": { "james-okafor": "<ix-profile-id>" } }'
    )


def _report_result(job_id, result: dict) -> None:
    """Write result back to Postgres + Redis results key."""
    ok  = result["ok"]
    res = result["result"]
    failure_type = result.get("failure_type") or ("none" if ok else "unknown")

    if ok:
        status = "applied"
    elif failure_type == "assessment_needed":
        status = "assessment_needed"
    elif failure_type in ("captcha", "session_expired", "timeout", "not_found", "duplicate"):
        status = "failed"
    else:
        status = "failed"

    result_str = json.dumps(res) if isinstance(res, dict) else str(res)
    _mcp_call("update_job_status", job_id=job_id, status=status, result=result_str[:4000])
    _rpush(RESULTS_KEY, json.dumps({
        "job_id": job_id, "ok": ok,
        "status": status,
        "failure_type": failure_type,
        "result": result_str[:1000],
    }))
    print(f"[job {job_id}] status={status} failure={failure_type}")


def process_queue(once: bool = False, workers: int = 1) -> None:
    """
    Poll Redis queue and dispatch jobs.

    workers=1  → sequential (safe for single IXBrowser instance)
    workers>1  → batch-drain up to N jobs, run concurrently via ConcurrentApplicationRunner
    """
    hostname = socket.gethostname()
    print(f"Queue bridge [{hostname}] workers={workers} polling {APPROVED_KEY} every {POLL_INTERVAL}s")

    if workers > 1:
        _process_queue_concurrent(once=once, workers=workers)
    else:
        _process_queue_sequential(once=once)


def _process_queue_sequential(once: bool) -> None:
    while True:
        payload_str = _lpop(APPROVED_KEY)
        if payload_str:
            try:
                payload = json.loads(payload_str)
            except Exception:
                payload = {"raw": payload_str}

            job_id = payload.get("job_id", "?")
            print(f"\n[job {job_id}] {payload.get('url', '?')[:80]}")
            _mcp_call("update_job_status", job_id=job_id, status="applying")
            result = dispatch_job(payload)
            if not result["ok"]:
                print(f"[job {job_id}] error: {str(result['result'])[:300]}", flush=True)
            _report_result(job_id, result)
        elif once:
            print("Queue empty.")
            break
        else:
            time.sleep(POLL_INTERVAL)


def _process_queue_concurrent(once: bool, workers: int) -> None:
    from careerbridge.application_pipeline import ConcurrentApplicationRunner

    async def _loop() -> None:
        runner = ConcurrentApplicationRunner(workers=workers)
        while True:
            # Drain up to `workers` items in one batch
            payloads = []
            for _ in range(workers):
                raw = _lpop(APPROVED_KEY)
                if raw:
                    try:
                        payloads.append(json.loads(raw))
                    except Exception:
                        payloads.append({"raw": raw})

            if not payloads:
                if once:
                    print("Queue empty.")
                    return
                await asyncio.sleep(POLL_INTERVAL)
                continue

            # Mark all as "applying" before starting
            for p in payloads:
                jid = p.get("job_id", "?")
                _mcp_call("update_job_status", job_id=jid, status="applying")
                print(f"\n[job {jid}] {p.get('url', '?')[:80]}")

            # Build configs — lightweight (no IXBrowser open yet; dispatch_job handles that)
            # For concurrent mode each config goes through its own dispatch_job
            # We run them all concurrently in threads since dispatch_job is sync
            import concurrent.futures
            with concurrent.futures.ThreadPoolExecutor(max_workers=workers) as pool:
                futures = {pool.submit(dispatch_job, p): p for p in payloads}
                for future in concurrent.futures.as_completed(futures):
                    payload = futures[future]
                    job_id = payload.get("job_id", "?")
                    try:
                        result = future.result()
                    except Exception as e:
                        result = {"ok": False, "result": str(e), "failure_type": "unknown"}
                    if not result["ok"]:
                        print(f"[job {job_id}] error: {str(result['result'])[:300]}")
                    _report_result(job_id, result)

            if once and not _lpop(APPROVED_KEY):
                print("Queue empty.")
                return

    asyncio.run(_loop())


def main():
    parser = argparse.ArgumentParser(description="CareerBridge desktop application dispatcher")
    parser.add_argument("--once",          action="store_true", help="Process queue then exit")
    parser.add_argument("--workers",       type=int, default=1,
                        help="Number of concurrent jobs (default 1; >1 uses thread pool)")
    parser.add_argument("--list-profiles", action="store_true",
                        help="List IXBrowser profiles and exit")
    args = parser.parse_args()

    if args.list_profiles:
        list_ix_profiles()
    else:
        process_queue(once=args.once, workers=args.workers)


if __name__ == "__main__":
    main()
