# Skill: Discovery Quality Gate (Subagent)

Invoke with: `/discover-and-gate [limit=N]`

This skill deploys parallel subagents to pull unenriched jobs from VPS postgres,
classify them through the Claude quality gate, and write clean records back —
replacing the heuristic Firecrawl/Crawlee filter with LLM judgment.

---

## When to use

- After the VPS discovery cron has run and new jobs are waiting in `status=pending, enriched=FALSE`
- After school discovery to re-score and validate enrollment URLs
- Any time you suspect the DB has stale/contaminated records (professional jobs, blog posts, wrong URLs)

---

## Execution procedure

### Step 1 — Count unenriched work

Call `mcp__vps__get_unenriched_jobs(limit=1)` to check how many jobs need processing.
Report the count to the user. If 0, say so and stop.

### Step 2 — Spawn parallel gate subagents

Split the unenriched batch into groups of 20. For each group, spawn a subagent with:

```
subagent_type: general-purpose
prompt: |
  You are a quality gate for a gig-work job discovery pipeline.

  For each job below, call mcp__vps__get_unenriched_jobs to confirm it still needs
  enrichment, then:

  1. Use the job URL to determine the domain/company.
  2. Classify:
     - BLOCK if: professional/licensed role (SWE, doctor, lawyer, accountant,
       engineer, director, C-suite), blog post, HN comment, school enrollment page,
       or any role requiring a degree or professional license.
     - KEEP if: gig task (annotation, transcription, translation, rating, testing,
       content writing, virtual assistant, GPT/survey, customer support, tutoring, moderation).
  3. For KEEP jobs:
     - Assign job_type from: ai_training, data_annotation, search_rating,
       transcription, translation, content_writing, social_media, virtual_assistant,
       customer_support, microtask, tutoring, testing, moderation, gpt, other_gig
     - Extract a 2-3 sentence requirements summary from the job description or URL domain.
     - Call mcp__vps__update_job_enrichment(job_id, official_url, official_description,
       job_type=<type>) to mark it enriched.
  4. For BLOCK jobs:
     - Call mcp__vps__update_job_status(job_id, status="blocked",
       result=<block_reason>) to remove it from the pending queue.

  Jobs to process: [INSERT BATCH HERE]

  Report back: {kept: N, blocked: N, errors: N, job_types: {type: count}}
```

### Step 3 — Collect and summarise

Wait for all subagents. Merge their reports:
- Total kept, total blocked, error count
- Job type distribution across all batches
- Any jobs that errored (retry individually or flag)

### Step 4 — Schools (optional, run after jobs)

If the user also wants school validation, call
`mcp__schools__list_confirmed_schools(min_score=0, limit=500)` and for each
score=0 school, spawn a subagent that:
1. Firecrawls the school URL
2. Re-analyzes against the 6 criteria using the same prompt as `schools_mcp/_analyzer.py`
3. Updates the score if evidence found

Report: how many schools moved from score=0 to score>=1.

---

## Hard rules for subagents

- Subagents read job data via `mcp__vps__*` tools only — no direct postgres queries
- Subagents never call `cdp_eval` with click patterns (hook blocks it anyway)
- Subagents report structured JSON: `{kept, blocked, errors, job_types}`
- Main agent writes all DB updates — subagents return verdicts, main executes

---

## Expected output to user

```
Discovery gate complete.
  Processed : 160 jobs
  Kept      : 43  (ai_training:12, data_annotation:9, gpt:8, transcription:7, ...)
  Blocked   : 117 (professional_job:89, blog_post:19, school_page:9)
  Errors    : 0

Schools re-scored: 14 moved from 0 → ≥1 (monthly_enrollment, no_transcript_required)
```
