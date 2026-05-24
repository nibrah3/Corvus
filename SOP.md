# CareerBridge — Standard Operating Procedure

> **Purpose:** Repeatable, step-by-step runbook for deploying, operating, and troubleshooting the CareerBridge automated job-application and assessment system.

---

## Table of Contents

1. [Architecture Overview](#1-architecture-overview)
2. [One-Time Setup](#2-one-time-setup)
3. [Daily Startup Checklist](#3-daily-startup-checklist)
4. [Running the Test Suite](#4-running-the-test-suite)
5. [Running a Job Campaign](#5-running-a-job-campaign)
6. [Adding a New Candidate Profile](#6-adding-a-new-candidate-profile)
7. [Human Gate (Approval Workflow)](#7-human-gate-approval-workflow)
8. [VPS Redis Tunnel](#8-vps-redis-tunnel)
9. [IXBrowser Profile Management](#9-ixbrowser-profile-management)
10. [Troubleshooting Reference](#10-troubleshooting-reference)
11. [Key Files & Environment Variables](#11-key-files--environment-variables)

---

## 1. Architecture Overview

```
IXBrowser (paid) ──► API port 53200 ──► ws://127.0.0.1:PORT/devtools/browser/UUID
                                                   │
                                          CDPExecutor.connect_ws()
                                          (routes browser-level URL → page session)
                                                   │
                               ┌───────────────────┴────────────────────┐
                               │                                        │
                    AssessmentPipeline                      ApplicationPipeline
                    (MCQ/radio fill)                        (browser-use agent)
                    OpenRouter → LLM                        OpenRouter → gpt-4o-mini
                    (gpt-4o-mini via OpenRouter)            (DOM-only, no vision)
                               │                                        │
                    human_gate=True?                        human_gate=True?
                               │                                        │
                    Gate Client ──► Redis (VPS tunnel) ──► Telegram/Dashboard
```

**Key design decisions:**
- `use_vision=False` on ApplicationPipeline — DOM extraction is 2200ms faster than screenshots
- `BROWSER_USE_MODEL=openai/gpt-4o-mini` — avoids Amazon Bedrock routing (which rejects integer `minimum` in JSON schema)
- `suppress_origin=True` on all WebSocket connections — bypasses Chrome 111+ Origin header rejection
- LLM response parsing: strip markdown fences → try direct `json.loads` → regex fallback `\[.*?\]`

---

## 2. One-Time Setup

### 2.1 Python environment

```powershell
cd D:\cb-core
py -3 -m pip install -r requirements.txt
py -3 -m pip install litellm websocket-client openai
```

### 2.2 .env file

Create `D:\cb-core\.env` with:

```env
# OpenRouter
OPENROUTER_API_KEY=sk-or-v1-...

# Model routing (MUST avoid Bedrock for browser-use)
BROWSER_USE_MODEL=openai/gpt-4o-mini
OPENROUTER_MODEL_VISION=openai/gpt-4o-mini
OPENROUTER_MODEL_REASONING=openai/gpt-4o-mini
OPENROUTER_MODEL_ASSESSMENT=openai/gpt-4o-mini

# Telegram notifications (optional)
TELEGRAM_TOKEN=...
TELEGRAM_CHAT_ID=...

# Redis gate (via VPS tunnel)
REDIS_HOST=127.0.0.1
REDIS_PORT=6380

# IXBrowser API (local, no key needed)
IXBROWSER_API=http://127.0.0.1:53200
```

### 2.3 IXBrowser profiles

| Profile ID | Candidate        | Proxy/Region | Kernel |
|------------|------------------|--------------|--------|
| 12         | Corvus (test)    | —            | 145    |
| 14         | James Okafor     | GB proxy     | 142 ⚠  |

> ⚠ Kernel 142 must be downloaded via the IXBrowser client before profile 14 can open.
> Open IXBrowser → Profiles → Profile 14 → Launch. If it prompts to download kernel, do so.

### 2.4 Verify IXBrowser is running

IXBrowser must be open (system tray) and its API server must be on port 53200.

```powershell
# Quick check
Invoke-WebRequest -Uri http://127.0.0.1:53200/api/v2/profile/list -Method POST -Body '{}' -ContentType 'application/json' | Select-Object -ExpandProperty Content
```

---

## 3. Daily Startup Checklist

Run these in order every day before any campaign:

```
[ ] 1. Open IXBrowser (system tray icon visible)
[ ] 2. If using VPS gate: run scripts\vps_tunnel.ps1 (see §8)
[ ] 3. Run E2E smoke test:  py -3 scripts/test_e2e.py --api-only
[ ] 4. All 5 tests PASS (gate_client will SKIP if tunnel not up — that's fine)
[ ] 5. If assessment_pipeline shows llm=0 or actions=0, re-run; intermittency is rare
```

---

## 4. Running the Test Suite

### Full suite (all 8 tests)

```powershell
cd D:\cb-core
py -3 scripts/test_e2e.py
```

### API-only (tests 1–6, skips free-profile and application pipeline)

```powershell
py -3 scripts/test_e2e.py --api-only
```

### Single test

```powershell
py -3 scripts/test_e2e.py --test 4      # assessment pipeline only
py -3 scripts/test_e2e.py --test 8      # application pipeline only
```

### Expected baseline results

```
✅  ixbrowser_api         PASS -- profile_id=12 cdp=ws://127.0.0.1:PORT/devtools/browser/...
✅  cdp_connection         PASS -- axtree=9 nodes, title='Example Domain', offset=(x,y)
✅  humanizer              PASS -- windmouse=Npts, move=ok, backend=pynput
✅  assessment_pipeline    PASS -- pages=4-5 llm=4-5 actions=20-35
✅  screenshot_vs_dom      PASS -- DOM: 2-5ms | Screenshot: 2100-2300ms | DOM FASTER
⏭  gate_client            SKIP -- Redis not reachable (tunnel not up)
✅  ixbrowser_free         PASS -- port=PORT
✅  application_pipeline   PASS -- status=failed steps=5-9 llm=5-9 (not_found/login wall)
```

> `application_pipeline` PASS with `status=failed` is correct — a `not_found` or login wall is an expected live-site outcome, not a code error.

---

## 5. Running a Job Campaign

### 5.1 Assessment only (e.g., 16personalities)

```python
from careerbridge.assessment_pipeline import AssessmentPipeline, AssessmentConfig
from careerbridge.ixbrowser_connector import ix_open_profile

cdp_url = ix_open_profile(14)  # or 12 for test

class Profile:
    name = "James Okafor"
    email = "james.okafor@example.com"
    class big_five:
        openness          = 0.65
        conscientiousness = 0.70
        extraversion      = 0.55
        agreeableness     = 0.75
        neuroticism       = 0.35

cfg = AssessmentConfig(
    cdp_url=cdp_url,
    url="https://www.16personalities.com/free-personality-test",
    profile=Profile(),
    human_gate=False,   # True = pause before each submit for human approval
    max_pages=12,
    page_timeout_s=25.0,
)
result = AssessmentPipeline(cfg).run()
print(result)
```

### 5.2 Full application (browser-use agent)

```python
import asyncio
from careerbridge.application_pipeline import ApplicationPipeline, ApplicationConfig
from careerbridge.ixbrowser_connector import ix_open_profile

cdp_url = ix_open_profile(14)

cfg = ApplicationConfig(
    cdp_url=cdp_url,
    url="https://jobs.company.com/apply/12345",
    profile={
        "name":     "James Okafor",
        "email":    "james.okafor@example.com",
        "phone":    "+44 7700 900123",
        "location": "London, UK",
        "bio":      "3 years fintech software engineering.",
        "skills":   '["Python","SQL","REST APIs","Git"]',
    },
    task_type="application",
    max_steps=15,
    timeout_s=300,
    job_id="job-001",
)
result = asyncio.run(ApplicationPipeline(cfg).run())
print(result)
```

---

## 6. Adding a New Candidate Profile

1. **IXBrowser:** Create a new browser profile with the candidate's proxy/fingerprint. Note the profile ID.
2. **Kernel:** Ensure the required kernel is downloaded. Launch the profile once manually to confirm it opens.
3. **Big Five scores:** Measure or estimate the candidate's personality scores (0.0–1.0 per trait).
4. **Test:** Run `py -3 scripts/test_e2e.py --test 1 --profile NEW_ID` to verify the profile opens.
5. **Campaign config:** Use the new profile ID in `ix_open_profile(NEW_ID)` calls.

---

## 7. Human Gate (Approval Workflow)

When `human_gate=True` is set, the pipeline pauses before each form submission and writes a gate record to Redis. A human (via Telegram bot or dashboard) must approve or modify the answer before the agent proceeds.

**Workflow:**

```
Pipeline fills form → pauses → writes to Redis gate →
Telegram bot shows draft → human replies "approve" / edits →
gate_client receives answer → pipeline submits
```

**To enable:**
- VPS tunnel must be running (§8)
- Set `human_gate=True` in `AssessmentConfig` / `ApplicationConfig`
- Have Telegram bot running on VPS or use dashboard

**Gate client test (dry-run):**
```powershell
py -3 scripts/test_e2e.py --test 6
```

---

## 8. VPS Redis Tunnel

The human gate communicates via Redis on the VPS. A local SSH tunnel maps `localhost:6380 → VPS:6379`.

**Start the tunnel:**

```powershell
# scripts\vps_tunnel.ps1
ssh -N -L 6380:127.0.0.1:6379 user@your-vps-ip
```

Or create `scripts\vps_tunnel.ps1`:

```powershell
# Keep running (reconnects on drop)
while ($true) {
    Write-Host "$(Get-Date) Starting VPS tunnel..."
    ssh -o ServerAliveInterval=30 -N -L 6380:127.0.0.1:6379 user@your-vps-ip
    Start-Sleep -Seconds 5
}
```

**Verify tunnel is up:**

```powershell
Test-NetConnection -ComputerName 127.0.0.1 -Port 6380
```

Once the tunnel is up, `py -3 scripts/test_e2e.py --test 6` will change from SKIP to PASS.

---

## 9. IXBrowser Profile Management

### List all profiles

```powershell
py -3 scripts/list_profiles.py
```

### Open a specific profile

```powershell
py -3 scripts/open_profile.py 12   # or any profile ID
```

### Check which kernel a profile needs

Open IXBrowser client → Profiles → hover/click profile → check "Browser Kernel" field.

Download missing kernels: IXBrowser client → Settings → Kernel Management.

### Free-account path (psutil scan)

If not using the paid API, open the profile manually in IXBrowser, then:

```powershell
py -3 scripts/test_e2e.py --test 7   # discovers open free profile via port scan
```

---

## 10. Troubleshooting Reference

### "403 Forbidden - Rejected an incoming WebSocket connection"

**Cause:** Chrome 111+ rejects WebSocket connections where the `Origin` header contains a port number.  
**Fix:** Already applied — `suppress_origin=True` in `CDPExecutor.connect()` and `connect_ws()`.  
**If it recurs:** Ensure you're using `websocket-client >= 1.9.0`.

```powershell
py -3 -m pip show websocket-client
```

### "getaddrinfo failed" or DNS error when connecting CDP

**Cause:** Passing a `ws://` URL string to `CDPExecutor.connect()` (which expects an int port).  
**Fix:** Use `CDPExecutor.connect_ws(ws_url)` for ws:// URLs from `ix_open_profile()`.

### Assessment pipeline: `llm=0, actions=0`

**Cause:** LLM returned empty or unparseable response.  
**Fixes already in place:**
1. Plain string system message (not Anthropic cache_control format)
2. `_get_page_context()` extracts question text for context
3. Regex fallback `re.search(r"\[.*?\]", raw, re.DOTALL)` handles explanation-then-JSON responses

**If it persists:** Run `py -3 scripts/test_llm_with_context.py` to test LLM call in isolation.

### "No module named 'litellm'" or import error

```powershell
py -3 -m pip install litellm browser-use openai websocket-client
```

### Bedrock JSON schema error (`minimum` property rejected)

**Cause:** `anthropic/claude-*` via OpenRouter routes to Amazon Bedrock which rejects integer `minimum` fields.  
**Fix:** Set in `.env`:

```env
BROWSER_USE_MODEL=openai/gpt-4o-mini
```

### IXBrowser profile won't open (kernel not found)

Open IXBrowser client, launch profile manually, download required kernel when prompted.  
Profile 14 needs kernel 142; profile 12 needs kernel 145.

### application_pipeline fails with `steps=0` and import error

This is a hard crash. Check the `error` field in the result — usually a missing package.  
Install the missing package and re-run.

### RedisConnectionError / gate_client test fails

VPS tunnel is not running. Start `scripts\vps_tunnel.ps1` first.

---

## 11. Key Files & Environment Variables

### Key source files

| File | Purpose |
|------|---------|
| `careerbridge/cdp_executor.py` | Raw CDP WebSocket client. `connect_ws(ws_url)` for IXBrowser URLs. |
| `careerbridge/ixbrowser_connector.py` | Opens IXBrowser profile via API, returns ws:// CDP URL. |
| `careerbridge/assessment_pipeline.py` | Fills MCQ/radio assessments using LLM. |
| `careerbridge/application_pipeline.py` | browser-use agent for full job applications. |
| `careerbridge/gate_client.py` | Redis-backed human approval gate. |
| `careerbridge/humanizer_mcp/` | Mouse movement humanization (windmouse). |
| `scripts/test_e2e.py` | 8-test end-to-end test suite. |
| `scripts/list_profiles.py` | List IXBrowser profiles. |
| `scripts/open_profile.py` | Open specific IXBrowser profile. |
| `scripts/test_llm_with_context.py` | Test assessment LLM call in isolation. |
| `scripts/dump_axtree.py` | Dump answerable nodes from a live page. |
| `scripts/vps_tunnel.ps1` | SSH tunnel to VPS Redis (create if needed). |

### Environment variables

| Variable | Default | Purpose |
|----------|---------|---------|
| `OPENROUTER_API_KEY` | — | OpenRouter API key (required) |
| `BROWSER_USE_MODEL` | `openai/gpt-4o-mini` | Model for browser-use agent (avoid Bedrock) |
| `OPENROUTER_MODEL_ASSESSMENT` | `openai/gpt-4o-mini` | Model for assessment MCQ filling |
| `OPENROUTER_MODEL_VISION` | `openai/gpt-4o-mini` | Vision model (unused when use_vision=False) |
| `TELEGRAM_TOKEN` | — | Bot token for human gate notifications |
| `TELEGRAM_CHAT_ID` | — | Chat ID for Telegram notifications |
| `REDIS_HOST` | `127.0.0.1` | Redis host (via VPS tunnel) |
| `REDIS_PORT` | `6380` | Redis port (local tunnel port) |
| `IXBROWSER_API` | `http://127.0.0.1:53200` | IXBrowser local API endpoint |

---

*Last updated: 2026-05-23*
