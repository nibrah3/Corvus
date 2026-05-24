# Corvus_Careebridge — Project Status & Blockers

*Last updated: 2026-05-21*

---

## Current Environment

| Item | Value |
|---|---|
| Machine | DESKTOP-5OP0RFK |
| User | HP |
| Clone path | `D:\cb-core` |
| Python | 3.14.0 at `C:\Python314\python.exe` |
| OS | Windows 11 Pro 10.0.26200 |

---

## System Status

### MCP Servers

All 9 MCP HTTP servers are running:

| Port | Server | Status | Notes |
|---|---|---|---|
| 8701 | humanizer_mcp | ✅ UP | |
| 8702 | capture_mcp | ✅ UP | Required Pillow install |
| 8703 | uia_mcp | ✅ UP | |
| 8704 | browser_mcp | ✅ UP | |
| 8705 | gemini_mcp | ✅ UP | |
| 8706 | telegram_mcp | ✅ UP | |
| 8707 | answer_mcp | ✅ UP | |
| 8708 | sqlite_mcp | ✅ UP | |
| 8709 | memory_mcp | ✅ UP | |

### Startup

To start all servers manually:
```powershell
powershell -File D:\cb-core\scripts\start_mcps.ps1
```

To register as a Windows startup task (run once as admin):
```powershell
powershell -File D:\cb-core\scripts\register_startup.ps1
```

---

## Setup Steps Completed (2026-05-21)

1. **Cloned repo** to `D:\cb-core` (E: drive is CD-ROM, not writable)
2. **Patched all `D:\cb-core` path references** → `D:\cb-core` across 11 files
3. **Installed Python 3.14.0** to `C:\Python314`
4. **Tightened Python directory permissions** (`C:\Python314`):
   - Removed `NT AUTHORITY\Authenticated Users: Modify` (security risk)
   - Added `HP: Full Control` explicitly for pip installs
   - Final ACL: HP (F), Administrators (F), SYSTEM (F), Users (RX)
5. **Installed missing package**: `pillow==12.2.0` (required by capture_mcp)
6. **Verified all 9 MCP servers** listening on ports 8701–8709

---

## Feature Completeness

| Feature | Status | Notes |
|---|---|---|
| Core FSM assessment loop | ✅ Complete | INIT→NAVIGATE→WAIT_UI→EXTRACT→REASON→EXECUTE→VERIFY→COMPLETE |
| Humanized mouse/keyboard | ✅ Complete | WindMouse paths, ex-Gaussian keystroke timing |
| Perception (OCR + UIA) | ✅ Complete | Frame diff + RapidOCR + Windows UI Automation |
| Reasoning (Claude via OpenRouter) | ✅ Complete | **Uses Haiku 4.5 — see blockers** |
| Persona system | ✅ Complete | Per-profile writing voice, deterministic seed |
| Multi-profile browser support | ✅ Complete | IXBrowser, GoLogin, native Chrome |
| MCP infrastructure (MinMCP) | ✅ Complete | Zero-dependency HTTP MCP, ~0.5s startup |
| Test suite | ✅ Complete | 4,674 lines across 8 phase files |
| Telegram notifications | ✅ Complete | Outbound-only |
| Remote Control (phone access) | ✅ Complete | Claude Code `--remote-control "CareerBridge"` |
| Gemini video analysis | 🟡 Partial | Upload/record/analyse working; main loop integration missing |
| SOP recording/playback | ❌ Stubbed | Schema exists (`SOP`, `SOPStep`), zero implementation |
| UFO bridge | 🟡 Experimental | Launcher + executor exist; main loop integration unclear |

---

## Blockers

### Critical

**1. No `requirements.txt` / `pyproject.toml`**
- Zero dependency lock file in the repo
- New installs require manual `pip install` for every package
- Only discovered missing package so far: `pillow` (caught at startup)
- Other packages (`dxcam`, `pywinauto`, `rapidocr-onnxruntime`, `windmouse`, `pyautogui`, `pynput`, `tenacity`, `openai`, `google-generativeai`, `pygetwindow`) may also be absent on a fresh machine
- **Fix**: Generate `requirements.txt` with `pip freeze` after full install, or write `pyproject.toml`

**2. Environment variables not configured**
- The following env vars are required and not set:
  - `OPENROUTER_API_KEY` — Claude/OpenRouter calls for answer generation
  - `GEMINI_API_KEY` — Gemini video/image analysis (Phase 2)
  - `TELEGRAM_ADMIN_CHAT_ID` — Telegram notification target
  - `CB_DB_PATH` — defaults to `D:\cb-core\careerbridge.db` (OK)
  - `CB_MEMORY_PATH` — defaults to `D:\cb-core\memory_store.json` (OK)
- System will silently fail or error at first tool call without these
- **Fix**: Create `D:\cb-core\.env` or set via System Properties → Environment Variables

**3. Task Scheduler startup not registered**
- `register_startup.ps1` has not been run on this machine
- MCPs do not auto-start at login yet
- **Fix**: Run `powershell -File D:\cb-core\scripts\register_startup.ps1` as Administrator once

### High Priority

**4. Claude reasoner uses Haiku, not Sonnet**
- `careerbridge/reasoning/claude_reasoner.py` hardcodes `anthropic/claude-haiku-4.5`
- `CLAUDE.md` explicitly states: *"Do NOT downgrade to Haiku for assessment answers — quality matters"*
- **Fix**: Change model to `anthropic/claude-sonnet-4-6` in `claude_reasoner.py`

**5. No database schema**
- `careerbridge.db` does not exist yet on this machine (no baseline data)
- Schema is undocumented — only known tables are `tasks` and `incoming` (legacy)
- **Fix**: Export schema from original machine: `sqlite3 careerbridge.db ".schema" > schema.sql` and commit

**6. No MCP health check / auto-restart**
- If any MCP server crashes, it stays down silently
- No watchdog process; manual restart required (see `docs/mcp_restart_guide.md`)
- **Fix**: Add a lightweight health-check loop to `start_agent.ps1` that restarts downed servers

### Medium Priority

**7. Hard-coded `E:\careerbridge\runtime\.env` path**
- `careerbridge/run_gemini_assessment.py` line 22 still references `E:\careerbridge\runtime\.env` as a fallback for `OPENROUTER_API_KEY`
- This path does not exist on this machine
- **Fix**: Update to `D:\cb-core\.env` or use `python-dotenv` with a configurable path

**8. Persona profiles directory missing**
- `answer_mcp` expects profiles at `D:\cb-core\profiles\{profile_id}.json`
- Directory does not exist yet
- **Fix**: `mkdir D:\cb-core\profiles`

**9. Memory store grows unbounded**
- `memory_store.json` has no pruning, rotation, or size cap
- Will grow indefinitely across sessions
- **Fix**: Add max-entry limit or archiving to `memory_mcp/server.py`

**10. Gemini + UFO integration paths are incomplete**
- `run_gemini_assessment.py` exists but is not wired into the main orchestrator
- UFO bridge (`ufo_launcher.py`, `ufo_executor.py`) depends on `E:\UFO-test` which does not exist on this machine
- **Fix**: Either integrate or formally mark as Phase 2 / deferred

---

## Immediate Next Steps (in order)

1. Set environment variables (`OPENROUTER_API_KEY`, `TELEGRAM_ADMIN_CHAT_ID`)
2. Create `D:\cb-core\profiles\` directory
3. Run `register_startup.ps1` as admin to enable boot autostart
4. Fix Claude reasoner model: Haiku → Sonnet in `claude_reasoner.py`
5. Install remaining pip dependencies and generate `requirements.txt`
6. Export `schema.sql` from original machine and commit
7. Test end-to-end with a real assessment URL via Remote Control

---

## Known Working

- All 9 MCP servers start and respond correctly
- Python 3.14.0 installed and accessible at `C:\Python314\python.exe`
- `start_mcps.ps1` correctly detects already-running servers and skips them
- Path references fully migrated from `D:\cb-core` → `D:\cb-core`
