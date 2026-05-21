"""
queue_bridge.py — Polls corvus:approved_jobs Redis queue and dispatches
each job to careerbridge/run_assessment.py for execution.

Called by Desktop Claude Code as a tool, not a standalone daemon.
vps_mcp must be running on localhost:8713 before calling this.

Usage:
    python scripts/queue_bridge.py [--once]

  --once   Process all currently queued jobs then exit (default: loop forever)
"""
from __future__ import annotations

import argparse
import datetime
import json
import os
import socket
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

CB_DIR  = Path(__file__).resolve().parent.parent
PYTHON  = os.environ.get("CB_PYTHON", "C:/Python314/python.exe")
RUN_ASSESSMENT = str(CB_DIR / "careerbridge" / "run_assessment.py")

REDIS_HOST     = "127.0.0.1"
REDIS_PORT     = 6380
APPROVED_KEY   = "corvus:approved_jobs"
RESULTS_KEY    = "corvus:job_results"
POLL_INTERVAL  = 15  # seconds

VPS_MCP_URL    = "http://localhost:8713/mcp"

# Default BigFive/behavior values for profiles missing these fields.
# Represents a measured, conscientious, moderately agreeable candidate —
# appropriate for AI training / data annotation gig work.
_DEFAULT_BIG_FIVE = {
    "openness": 0.70,
    "conscientiousness": 0.75,
    "extraversion": 0.45,
    "agreeableness": 0.65,
    "neuroticism": 0.30,
}
_DEFAULT_RESPONSE_BIAS = {
    "extreme_answer_rate": 0.15,
    "neutral_preference": 0.25,
    "social_desirability_bias": 0.40,
    "consistency_strength": 0.80,
}
_DEFAULT_LINGUISTIC = {
    "verbosity": 0.55,
    "formality": 0.65,
    "optimism": 0.60,
}
_DEFAULT_BEHAVIOR = {
    "typing_wpm": 62,
    "error_rate": 0.02,
    "mouse_speed": "medium",
    "pause_min_ms": 180,
    "pause_max_ms": 900,
}


# ── Redis helpers ──────────────────────────────────────────────────────────────

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


# ── VPS MCP helper ─────────────────────────────────────────────────────────────

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
        with urllib.request.urlopen(req, timeout=15) as r:
            resp = json.loads(r.read())
        content = resp["result"]["content"][0]["text"]
        return json.loads(content)
    except Exception as e:
        return {"error": str(e)}


# ── Profile fetch + shape ─────────────────────────────────────────────────────

def _build_profile_payload(profile_id: str) -> dict | None:
    """
    Fetch profile from VPS postgres via vps_mcp and return the dict shape
    that careerbridge/persistence.py profile_from_dict() expects.
    """
    raw = _mcp_call("get_profile", profile_id=profile_id)
    if "error" in raw:
        print(f"  [profile] fetch error: {raw['error']}", file=sys.stderr)
        return None

    # Parse JSON fields stored as strings in postgres
    def _parse(field: str, default: dict) -> dict:
        val = raw.get(field)
        if not val:
            return default
        if isinstance(val, dict):
            return val
        try:
            return json.loads(val)
        except Exception:
            return default

    big_five        = _parse("big_five",       _DEFAULT_BIG_FIVE)
    response_bias   = _parse("response_bias",  _DEFAULT_RESPONSE_BIAS)
    linguistic      = _parse("linguistic_traits", _DEFAULT_LINGUISTIC)
    behavior        = _parse("behavior",        _DEFAULT_BEHAVIOR)

    # Fill any missing sub-keys with defaults
    for k, v in _DEFAULT_BIG_FIVE.items():
        big_five.setdefault(k, v)
    for k, v in _DEFAULT_RESPONSE_BIAS.items():
        response_bias.setdefault(k, v)
    for k, v in _DEFAULT_LINGUISTIC.items():
        linguistic.setdefault(k, v)
    for k, v in _DEFAULT_BEHAVIOR.items():
        behavior.setdefault(k, v)

    return {
        "profile_id":      raw.get("id", profile_id),
        "name":            raw.get("name", ""),
        "big_five":        big_five,
        "response_bias":   response_bias,
        "linguistic_traits": linguistic,
        "behavior":        behavior,
        "created_at":      raw.get("created_at", datetime.datetime.utcnow().isoformat()),
        "runs":            0,
    }


# ── Dispatch ──────────────────────────────────────────────────────────────────

def dispatch_job(job_payload: dict) -> dict:
    """
    Run run_assessment.py for a single approved job.
    Returns {"ok": bool, "result": str | dict}.
    """
    job_id     = job_payload.get("job_id")
    url        = job_payload.get("url", "")
    profile_id = job_payload.get("profile_id", "")

    if not url:
        return {"ok": False, "result": "no URL in payload"}

    # Fetch complete profile from VPS
    profile_dict = _build_profile_payload(profile_id)
    if not profile_dict:
        return {"ok": False, "result": f"could not fetch profile '{profile_id}'"}

    payload = {
        "profile":      profile_dict,
        "url":          url,
        "sop":          None,          # None = discovery mode (no pre-recorded SOP)
        "goal":         "Apply for the job and complete any assessments.",
        "window_title": "IXBrowser",
    }

    print(f"  [dispatch] profile={profile_dict['name']!r} url={url[:80]}")

    try:
        proc = subprocess.run(
            [PYTHON, RUN_ASSESSMENT],
            input=json.dumps(payload),
            capture_output=True,
            text=True,
            timeout=3600,
            cwd=str(CB_DIR),
        )
        stdout = proc.stdout.strip()
        stderr = proc.stderr.strip()

        if proc.returncode != 0 and not stdout:
            return {"ok": False, "result": (stderr or "no output")[-2000:]}

        try:
            result_dict = json.loads(stdout)
            ok = result_dict.get("final_state") in ("complete", "completed")
            return {"ok": ok, "result": result_dict}
        except json.JSONDecodeError:
            return {"ok": False, "result": stdout[-2000:] or stderr[-2000:]}

    except subprocess.TimeoutExpired:
        return {"ok": False, "result": "timed out after 3600s"}
    except Exception as e:
        return {"ok": False, "result": str(e)}


# ── Main loop ─────────────────────────────────────────────────────────────────

def process_queue(once: bool = False):
    print(f"Queue bridge started. Polling {APPROVED_KEY} every {POLL_INTERVAL}s...")
    while True:
        payload_str = _lpop(APPROVED_KEY)
        if payload_str:
            try:
                payload = json.loads(payload_str)
            except Exception:
                payload = {"raw": payload_str}

            job_id = payload.get("job_id", "?")
            print(f"\n[{job_id}] -> {payload.get('url', '?')[:80]}")

            # Mark job as in-progress in postgres
            _mcp_call("update_job_status", job_id=job_id, status="applying")

            result = dispatch_job(payload)
            ok     = result["ok"]
            res    = result["result"]

            print(f"[{job_id}] done: ok={ok}")

            # Determine final status
            if ok:
                status = "applied"
            elif isinstance(res, dict) and res.get("final_state") == "assessment_needed":
                status = "assessment_needed"
            else:
                status = "failed"

            # Update postgres
            result_str = json.dumps(res) if isinstance(res, dict) else str(res)
            _mcp_call("update_job_status",
                      job_id=job_id,
                      status=status,
                      result=result_str[:4000])

            # Push to job_results so VPS monitor can pick it up
            _rpush(RESULTS_KEY, json.dumps({
                "job_id": job_id,
                "ok":     ok,
                "status": status,
                "result": result_str[:1000],
            }))

            print(f"[{job_id}] postgres → {status}")

        elif once:
            print("Queue empty — exiting (--once mode).")
            break
        else:
            time.sleep(POLL_INTERVAL)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--once", action="store_true",
                        help="Process current queue then exit")
    args = parser.parse_args()
    process_queue(once=args.once)


if __name__ == "__main__":
    main()
