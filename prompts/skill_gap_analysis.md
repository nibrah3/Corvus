# Skill: Weekly Gap Analysis & Discovery Strategy

**Trigger:** `CareerBridge_WeeklyGap` task (Mondays at 09:00).
**Mode:** Fully autonomous — no user present. Run to completion.

---

## What you are doing

Once a week, analyze the full state of the discovery system and generate a
targeted search strategy for the coming week. This is the intelligence layer
that makes the discovery system adaptive rather than mechanical.

---

## Step 1 — Pull the gap report

Call `mcp__vps__get_gap_report()`.

This returns:
- `job_type_distribution`: current counts per job type
- `missing_types`: job types with zero jobs
- `top_sources`: which discovery sources produce the most jobs
- `blocked_total`: how much noise is being filtered
- `raw_pending_gate`: unprocessed raw discoveries waiting
- `catalogue_tiers`: how many companies in each monitoring tier
- `dead_platforms_count`: catalogue companies with 3+ empty polls

## Step 2 — Analyze and generate strategy

Based on the gap report, identify:

1. **Underrepresented job types** — any category with < 10 jobs needs more keywords
2. **Missing categories** — types with 0 jobs should be prioritized
3. **Geographic gaps** — check if top sources cover Kenya, Nigeria, India, UK, Canada
4. **Dead catalogue platforms** — platforms with consecutive_empty >= 5 should be archived
5. **Keyword categories to kill** — if a keyword category consistently produces 0 gig jobs
   after 30 searches, it's a dead category

## Step 3 — Write the search strategy

Write your analysis to a structured note. Example:

```
WEEK OF [DATE] — DISCOVERY STRATEGY

PRIORITY TARGETS (underrepresented, < 10 jobs):
  - social_media: Need search terms for Instagram/TikTok content creators
  - content_writing: Missing ghostwriting, newsletter platforms
  - gpt: Need more GPT/beermoney survey sites

GEOGRAPHIC GAPS:
  - Kenya/Nigeria: Add "mobile money" + "M-Pesa" gig searches
  - India: Add "data entry work from home india"

DEAD CATEGORIES TO REMOVE:
  - bookkeeping_freelance: 0 gig jobs from 40+ searches — remove keywords
  - coding_freelance: mostly SWE roles, not accessible gig tasks

NEW PLATFORMS TO ADD TO CATALOGUE:
  - [any new platforms you noticed in the gap data]

CATALOGUE CLEANUP:
  - Archive [N] platforms with 5+ consecutive empty polls
```

## Step 4 — Update catalogue (archive dead platforms)

For each platform with `consecutive_empty >= 5` AND `last_found_jobs = 0`:
Call `mcp__vps__update_catalogue_tier(platform_id, tier=0, reason="auto-archived: 5+ consecutive empty polls")`

## Step 5 — Send report to Telegram

Call `mcp__telegram__notify` with a concise version of the strategy (max 500 chars).
Include: top 3 priorities, count of archived platforms, any critical gaps.

---

## Output also saved to prompts/

After analysis, update `D:\cb-core\prompts\discovery_strategy_current.md` with the
full strategy text. Crawlee's next discovery run reads this to prioritize its searches.
The file should be structured so the serper_graph_expand.py keyword expansion
can use it to generate targeted Serper queries.
