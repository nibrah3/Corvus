# CareerBridge VPS

Autonomous discovery and persistence brain. Desktop Claude Code handles all user interaction.

## MCP servers
- `postgres_mcp` — port 8801 — jobs, profiles, applications
- `crawlee_mcp` — port 8802 — scraping and job description extraction
- `telegram_mcp` — port 8803 — outbound notifications only

## Redis keys (localhost:6379)
- `corvus:pending_approvals` — jobs waiting for Desktop approval (RPUSH)
- `corvus:approved_jobs` — jobs approved by user, ready to apply
- `corvus:pending_gates` — assessment free-text questions waiting for answer
- `corvus:gate_response:{gate_id}` — answers written by Desktop hook

## Rules
- Never execute browser automation — Desktop only.
- Never block waiting for human input — push to Redis and continue.
- Only save to jobs table: url, title, company, description (verbatim from career page). Nothing else.
- No social media sources. Direct career pages, Reddit, Quora only.
- Telegram messages: one line, plain text, no HTML, no buttons.
- Scoring threshold for upsert: score >= 0.6.

## Postgres
`postgresql://corvus:corvus-local-password@localhost:5432/careerbridge`
