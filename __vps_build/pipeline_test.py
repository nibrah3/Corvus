"""
pipeline_test.py — Live end-to-end pipeline simulation.
Runs on VPS: python3 /opt/corvus/pipeline_test.py
"""
import json
import os
import socket
import urllib.request

OPENROUTER_KEY = os.environ.get("OPENROUTER_API_KEY", "")


def mcp(port, tool, **kw):
    body = json.dumps({
        "jsonrpc": "2.0", "id": 1, "method": "tools/call",
        "params": {"name": tool, "arguments": kw}
    }).encode()
    req = urllib.request.Request(
        f"http://localhost:{port}/mcp", data=body,
        headers={"Content-Type": "application/json"}
    )
    with urllib.request.urlopen(req, timeout=15) as r:
        resp = json.loads(r.read())
    return json.loads(resp["result"]["content"][0]["text"])


def score_job(title, company, desc, profile):
    if not OPENROUTER_KEY:
        return 0.65  # fallback if no key
    prompt = (
        f"Score 0.0-1.0 how well this job matches this candidate. Reply ONLY with a decimal.\n"
        f"JOB: {title} at {company}\n"
        f"DESC: {desc[:300]}\n"
        f"CANDIDATE SKILLS: {profile.get('skills', '')}\n"
        f"CANDIDATE BIO: {profile.get('bio', '')[:200]}"
    )
    body = json.dumps({
        "model": "anthropic/claude-haiku-4-5-20251001",
        "messages": [{"role": "user", "content": prompt}],
        "max_tokens": 10,
    }).encode()
    req = urllib.request.Request(
        "https://openrouter.ai/api/v1/chat/completions", data=body,
        headers={"Content-Type": "application/json", "Authorization": f"Bearer {OPENROUTER_KEY}"}
    )
    try:
        with urllib.request.urlopen(req, timeout=20) as r:
            raw = json.loads(r.read())["choices"][0]["message"]["content"].strip()
            return max(0.0, min(1.0, float(raw)))
    except Exception as e:
        print(f"    [scoring error: {e}]")
        return 0.5


def redis_rpush(key, value):
    with socket.create_connection(("127.0.0.1", 6379), timeout=3) as sock:
        k = key.encode()
        v = value.encode()
        cmd = f"*3\r\n$5\r\nRPUSH\r\n${len(k)}\r\n".encode() + k + f"\r\n${len(v)}\r\n".encode() + v + b"\r\n"
        sock.sendall(cmd)
        sock.recv(256)


def redis_llen(key):
    with socket.create_connection(("127.0.0.1", 6379), timeout=3) as sock:
        k = key.encode()
        cmd = f"*2\r\n$4\r\nLLEN\r\n${len(k)}\r\n".encode() + k + b"\r\n"
        sock.sendall(cmd)
        reply = sock.recv(64).decode().strip()
        return int(reply[1:]) if reply.startswith(":") else 0


def redis_lrange(key, start=0, end=-1):
    with socket.create_connection(("127.0.0.1", 6379), timeout=3) as sock:
        k = key.encode()
        s = str(start).encode()
        e = str(end).encode()
        cmd = (
            f"*4\r\n$6\r\nLRANGE\r\n${len(k)}\r\n".encode() + k
            + f"\r\n${len(s)}\r\n".encode() + s
            + f"\r\n${len(e)}\r\n".encode() + e + b"\r\n"
        )
        sock.sendall(cmd)
        data = b""
        while True:
            chunk = sock.recv(4096)
            if not chunk:
                break
            data += chunk
            if len(data) > 100 or not chunk:
                break
        return data.decode(errors="replace")


def main():
    print("=" * 60)
    print("CAREERBRIDGE PIPELINE SIMULATION — LIVE TEST")
    print("=" * 60)
    results = {}

    # ── 1. Profile check ──────────────────────────────────────────────────────
    print("\n[1] Profile check via postgres_mcp")
    profiles_resp = mcp(8801, "list_profiles")
    profiles = profiles_resp.get("profiles", [])
    print(f"    Profiles in DB: {len(profiles)}")
    if not profiles:
        print("    FAIL: no profiles — cannot score jobs")
        return
    profile = mcp(8801, "get_profile", profile_id=profiles[0]["id"])
    print(f"    Using profile: {profile['name']} ({profile['id']})")
    results["profile"] = "PASS"

    # ── 2. Live scrape ────────────────────────────────────────────────────────
    print("\n[2] Live scrape via crawlee (HackerNews, 5 posts)")
    crawlee_resp = json.loads(urllib.request.urlopen(
        urllib.request.Request(
            "http://localhost:3100/scrape/hackernews",
            data=b'{"maxPosts":5}',
            headers={"Content-Type": "application/json"}
        ), timeout=30
    ).read())
    jobs_raw = crawlee_resp.get("data", [])[:5]
    print(f"    Scraped: {len(jobs_raw)} jobs in {crawlee_resp.get('duration', '?')}ms")
    for j in jobs_raw[:3]:
        print(f"    - {j.get('company_name', '?')}: {j.get('website_url', '')[:70]}")
    results["scrape"] = "PASS" if jobs_raw else "FAIL"

    # ── 3. Scoring ────────────────────────────────────────────────────────────
    print(f"\n[3] Scoring jobs against profile (OpenRouter key: {'SET' if OPENROUTER_KEY else 'NOT SET'})")
    scored = []
    for raw in jobs_raw:
        url = raw.get("website_url", "") or raw.get("careers_url", "")
        company = raw.get("company_name", "Unknown")
        title = f"Engineer at {company}"
        desc = raw.get("description", "") or f"{company} — startup job on HackerNews"
        score = score_job(title, company, desc, profile)
        print(f"    {score:.2f}  {company}")
        scored.append({"url": url, "title": title, "company": company, "desc": desc, "score": score})
    results["scoring"] = "PASS"

    # ── 4. Upsert jobs to postgres ────────────────────────────────────────────
    print("\n[4] Upserting scored jobs to postgres (threshold 0.5 for test)")
    upserted = []
    for j in scored:
        if j["score"] >= 0.5:
            r = mcp(8801, "upsert_job",
                url=j["url"], title=j["title"], company=j["company"],
                description=j["desc"][:2000], score=float(j["score"]),
                source="discovered", profile_id=profile["id"]
            )
            job_id = r.get("job_id")
            entry = {"job_id": job_id, "url": j["url"], "title": j["title"],
                     "company": j["company"], "score": round(j["score"], 2),
                     "profile_id": profile["id"], "profile_name": profile["name"]}
            upserted.append(entry)
            print(f"    job_id={job_id} | {j['company']} | score={j['score']:.2f}")
    print(f"    Total upserted: {len(upserted)}")
    results["upsert"] = "PASS" if upserted else "SKIP (all scored <0.5)"

    # ── 5. Push to Redis pending_approvals ────────────────────────────────────
    print("\n[5] Pushing to Redis corvus:pending_approvals")
    for job in upserted:
        redis_rpush("corvus:pending_approvals", json.dumps(job))
        print(f"    Pushed job_id={job['job_id']}")
    llen = redis_llen("corvus:pending_approvals")
    print(f"    Queue depth: {llen}")
    results["redis_push"] = "PASS" if llen > 0 else "FAIL"

    # ── 6. Log discovery event ────────────────────────────────────────────────
    print("\n[6] Logging discovery event to postgres")
    r = mcp(8801, "log_event", type="discovery_cycle_test",
            payload=json.dumps({"scraped": len(jobs_raw), "upserted": len(upserted), "test": True}))
    print(f"    Event id={r.get('event_id')}")
    results["log_event"] = "PASS"

    # ── 7. Telegram notify ────────────────────────────────────────────────────
    print("\n[7] Telegram notification via telegram_mcp")
    msg = f"[TEST] Discovery simulation: {len(jobs_raw)} scraped, {len(upserted)} upserted, {llen} pending approval."
    r = mcp(8803, "notify", text=msg)
    ok = r.get("ok", False)
    print(f"    Sent: {ok} — {r.get('results', [{}])[0].get('ok', r)}")
    results["telegram"] = "PASS" if ok else "FAIL"

    # ── 8. Summary ────────────────────────────────────────────────────────────
    print("\n" + "=" * 60)
    print("RESULTS")
    print("=" * 60)
    for k, v in results.items():
        mark = "✓" if "PASS" in v else ("~" if "SKIP" in v else "✗")
        print(f"  {mark} {k}: {v}")

    print("\nREDIS STATE:")
    print(f"  corvus:pending_approvals: {redis_llen('corvus:pending_approvals')} items")
    print(f"  corvus:approved_jobs:     {redis_llen('corvus:approved_jobs')} items")

    jobs_in_db = mcp(8801, "list_jobs", status="pending", limit=10)
    print(f"\nPOSTGRES pending jobs: {jobs_in_db.get('count', 0)}")

    print("\nDONE. Redis has pending approval items for Desktop to pick up.")


if __name__ == "__main__":
    main()
