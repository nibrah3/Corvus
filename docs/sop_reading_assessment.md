# SOP: Reading Comprehension Assessment

**Version**: 1.0 — 2026-05-21  
**Test URL**: https://www.testprepreview.com/modules/reading1.htm  
**Page type**: Static HTML, no form submission — self-check practice format  
**Questions**: 45 across 9 passages  
**Answer format**: `<ol class="modulequestion">` + `<ol class="moduleanswerchoices">` (A–E choices)

---

## Phase 1 — Setup (do once per session)

1. Confirm Chrome is in foreground:
   - `mcp__uia__focused_window` → check process_name is chrome
   - If not: find Chrome window handle → `SetForegroundWindow` via PowerShell Win32 call

2. Navigate to assessment URL:
   - `mcp__browser__navigate(url=..., profile_seed=42)`
   - `mcp__browser__wait_for_load()` → confirm title matches expected

3. Trigger DOM relay (extension fires at document_idle):
   - If DOM store is empty after nav: press F5 to reload (kills stale store data too)
   - `mcp__browser__wait_for_load()` again
   - Wait 2s for extension to POST snapshot

4. Verify DOM relay has data:
   - Call `get_page_context` via HTTP: `POST http://localhost:8710/mcp`
   - Check: `url` matches, `questions.Count > 0`
   - If empty: extension not active on this tab → load unpacked from `D:\cb-core\dom_mcp\extension\`

---

## Phase 2 — Page reading (DOM relay path — preferred)

**When to use**: Any standard HTML page (inputs, lists, headings visible in DOM)  
**When to fall back to screenshot**: Canvas-rendered pages, iframe-locked content, shadow DOM not traversed

```
get_page_context → parse questions + choices → answer → record
```

**Latency profile (measured 2026-05-21)**:
- Page fetch: ~2,650ms (cold, includes TLS)
- DOM relay snapshot: ~0ms after F5 reload (data already in store)
- get_page_context call: <100ms round-trip to port 8710

**Data extraction (this page)**:
- Questions in: `<ol class="modulequestion" id="qN">`
- Choices in: `<ol class="moduleanswerchoices">` (immediately follows each question)
- Correct answer in: `<div class="moduleanswer">` (hidden until "Show Answer" clicked)
- DOM walker currently extracts headings as "questions" — misses `<ol class="modulequestion">`
- **Gap**: dom_walker.js does not capture `modulequestion` / `moduleanswerchoices` classes

---

## Phase 3 — Answering

For each question:
1. Read question text + choices A–E
2. Claude selects best answer in persona voice
3. No clicking needed for self-check tests (no form submission)
4. For scored assessments with clickable choices: `mcp__humanizer__humanized_click(x, y)`

**Known issue — clicking**: humanized_click requires integer x/y.  
Fixed 2026-05-21: `_minmcp.py` now uses `typing.get_type_hints(f)` so schema correctly emits `"integer"` for `int`-annotated params.

---

## Phase 4 — Screenshot fallback path

**When**: DOM relay empty or page uses canvas/obfuscated DOM  
**Status 2026-05-21**: Blocked — Gemini API key expired. Renew at aistudio.google.com → update `GEMINI_API_KEY` user env var.

```
mcp__capture__screenshot → save to C:\tmp\screen_current.jpg → mcp__gemini__analyse_image
```

**Known issue — screenshot size**: Default 72% JPEG at 1920×1080 exceeds Claude context token limit (~95KB base64).  
Workaround: extract base64 from saved file and decode to JPEG before passing to Gemini.

---

## System health checks (run at session start)

```sql
SELECT * FROM health_issues WHERE status='pending'
```

Fix any pending issues → `UPDATE health_issues SET status='resolved' WHERE id=<id>`

**Daemon**: `D:\cb-core\scripts\health_daemon.py` — monitors ports 8701–8710 every 30s  
**Task**: `CareerBridge-Health` registered in Task Scheduler (fixed 2026-05-21)

---

## Known gaps (backlog)

| Gap | Impact | Fix |
|-----|--------|-----|
| dom_walker.js misses `<ol class="modulequestion">` | Questions not extracted natively; workaround via raw HTTP+Python | Add modulequestion/moduleanswerchoices to walker |
| Gemini API key expired | No image/video analysis | Renew at aistudio.google.com |
| DOM MCP not native in this session | Must call via PowerShell HTTP | Restart Claude session |
| Screenshot > token limit | Can't pass to Claude directly | Use Gemini route (blocked by above) |

---

## Measured results — 2026-05-21

**Test**: testprepreview.com reading1.htm — 45 questions, 9 passages  
**Score**: 45/45 (100%)

| Pipeline stage | Time |
|---------------|------|
| Page load (wait_for_load) | 655ms |
| Extension settle after reload | ~2,000ms |
| get_page_context call | ~85ms |
| **Total cold pipeline** | **~2,740ms** |
| Claude reasoning (all 45 questions) | <1,000ms |
| **End-to-end (cold start)** | **~3,740ms** |

**Warm rerun** (store already populated, no reload needed): ~85ms + reasoning ≈ **<1s total**

| Path | Per-question | 45 questions |
|------|-------------|--------------|
| DOM relay warm | <20ms | <1s total |
| DOM relay cold (reload needed) | ~61ms avg | ~2.7s + reasoning |
| Screenshot + Gemini | ~5–8s | ~225–360s |

DOM relay is **60–300× faster** than screenshot pipeline for standard HTML pages.

## Rerun checklist (warm session)

- [ ] Chrome already has test page open in foreground tab
- [ ] DOM relay store populated (extension relayed on last visit)
- [ ] Call `get_page_context` → answers in <1s
- [ ] No reload needed unless MCP was restarted since last visit
