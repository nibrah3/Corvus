# CareerBridge — Operating Instructions

Last updated: 2026-05-20. This file is loaded at every Claude Code session start.

---

## System Architecture

**Claude Code is the brain.** It connects to 9 MCP HTTP servers running locally and one Remote Control tunnel for phone access. There is no separate bridge, listener, or worker process.

### MCP Servers (all HTTP, localhost)

| Port | Module | Purpose |
|------|--------|---------|
| 8701 | `humanizer_mcp` | OS-level mouse/keyboard with human timing curves |
| 8702 | `capture_mcp` | Screenshots and screen recording (DXcam primary) |
| 8703 | `uia_mcp` | Windows UI Automation element finder |
| 8704 | `browser_mcp` | Chrome control via keyboard shortcuts (no CDP) |
| 8705 | `gemini_mcp` | Screen recording + Gemini video/image analysis |
| 8706 | `telegram_mcp` | **Outbound-only** status channel (notify, send_screenshot) |
| 8707 | `answer_mcp` | Persona management + answer humanization |
| 8708 | `sqlite_mcp` | Direct SQLite access to `careerbridge.db` |
| 8709 | `memory_mcp` | Knowledge graph persistence (JSON store) |

### Remote Control

Claude Code runs with `--remote-control "CareerBridge"`. Connect from phone via the Claude mobile/web app → Sessions list → "CareerBridge". This is the primary control interface.

### Startup

All MCPs + the Remote Control session start automatically at Windows login via Task Scheduler (see `scripts/register_startup.ps1`). Entry point is `scripts/start_agent.ps1`.

---

## Behavioral Rules

### Communication style
- Conversational tone — no robotic step narration, no "I will now proceed to…" phrases.
- Before acting on anything significant: send a Telegram status (`mcp__telegram__notify`) AND present choices via `AskUserQuestion` (renders as clickable buttons in Claude Code UI).
- Keep Telegram messages short — status only, no essays.

### Decision gates
For any fork where the user must choose (e.g. which browser profile, which persona, IXBrowser vs GoLogin):
1. Call `mcp__telegram__notify` with the decision summary.
2. Call `AskUserQuestion` with the options as buttons.
3. Wait for selection, then proceed silently.

### Tool permissions
All Bash and MCP tools are pre-approved in `~/.claude/settings.json`. No approval prompts appear. If you see one, it means a new tool not yet in the allowlist.

---

## Assessment Workflow

### Phase overview
1. User sends assessment URL via Remote Control (Claude Code app).
2. Claude navigates to URL, takes a screenshot, identifies question type.
3. For each screen:
   - **Multiple choice** → UIA finds elements, Claude selects best option per persona, humanizer clicks it.
   - **Free text** → Claude writes answer in persona voice, presents via `AskUserQuestion` with the draft as a preview, user picks Approve / Edit / Regenerate before anything is typed.
4. Telegram notified on completion or error (with screenshot).

### Answer review flow (free-text questions)

1. Write the draft answer in a **code block** in the text response (copy button appears automatically).
2. Immediately follow with `AskUserQuestion`: options are **Approve**, **Edit**, **Regenerate**.
3. Also call `mcp__telegram__notify(text="Free-text question — waiting for your answer review.")`.
4. **Approve** → `humanized_type` the answer as shown.
5. **Edit** → user copies the code block, pastes their modified version directly into the chat message. Read their message and type that version verbatim.
6. **Regenerate** → write a new draft, loop back to step 1.

### Video fullscreen rule

Before starting any Gemini video recording or analysing any video content on screen:
1. `mcp__humanizer__humanized_hotkey(keys=["f11"])` — toggle fullscreen.
2. `mcp__browser__wait_for_load()` — wait for the transition to settle.
3. `mcp__capture__screenshot()` — confirm fullscreen before proceeding.
4. If fullscreen did not apply (e.g. embedded player), find and click the fullscreen button via `mcp__uia__find_elements` or `mcp__humanizer__humanized_click` on the player's fullscreen icon.
5. Only then call `mcp__gemini__start_recording()`.

When done recording, press F11 again to restore normal view before continuing.

### Tool routing
- **Screen analysis** → `mcp__capture__screenshot` → `mcp__gemini__analyse_image`
- **Element finding** → `mcp__uia__find_elements`
- **Clicking/typing** → `mcp__humanizer__humanized_click` / `mcp__humanizer__humanized_type`
- **Navigation** → `mcp__browser__navigate`, `mcp__browser__wait_for_load`
- **Answer quality** → Write answers directly as Claude (Sonnet) in persona voice. Do NOT call `mcp__answer__humanize_prose` for generation — only for post-processing if needed.

### Persona system
Personas live in `E:\cb-core\profiles\{profile_id}.json`:
```json
{
  "profile_id": "...",
  "facts": {"age": 28, "background": "...", "industry": "..."},
  "persona_prompt": "You are writing AS a specific person..."
}
```
- Load: read the JSON file directly.
- Check: `mcp__answer__get_persona(profile_id="...")`
- Create: `mcp__answer__assign_persona(profile_id="...", facts={...})`

---

## Error Handling

If anything fails during an assessment:
1. `mcp__capture__screenshot()` — capture current state.
2. `mcp__telegram__send_screenshot(image_path=..., caption="Error at: description")`.
3. `mcp__telegram__notify(text="Hit a snag: {description}. Screenshot sent.")`.
4. `mcp__sqlite__write_query` — mark the task status as 'error' in the DB.

---

## Model Routing

- **This session (Sonnet 4.6)**: orchestration, answer generation, reasoning.
- **Gemini**: screen/video analysis when context needs more than a still frame.
- **Do NOT downgrade to Haiku** for assessment answers — quality matters.

---

## Database Schema (careerbridge.db)

Key tables: `tasks`, `incoming` (legacy, no longer actively used). Query with `mcp__sqlite__read_query`.

---

## Starting the System Manually

```powershell
# Start all MCP servers (skips if already running)
powershell -File E:\cb-core\scripts\start_mcps.ps1

# Start the agent loop with Remote Control
powershell -File E:\cb-core\scripts\start_agent.ps1
```

To verify MCPs are live:
```powershell
8701,8702,8703,8704,8705,8706,8707,8708,8709 | ForEach-Object {
    $r = try { Invoke-WebRequest "http://localhost:$_/mcp" -Method Post -TimeoutSec 2 -ErrorAction Stop } catch { $null }
    "$_ " + $(if ($r) { "UP" } else { "DOWN" })
}
```
