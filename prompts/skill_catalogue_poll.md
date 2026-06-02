# Skill: Company Catalogue Poll

**Trigger:** `CareerBridge_Catalogue` task (every 6 hours).
**Mode:** Fully autonomous — no user present. Run to completion.

---

## What you are doing

The `discovered_platforms` table contains companies whose career pages should be
checked regularly for new gig listings. These are platforms confirmed to post
annotation, testing, transcription, translation, and similar task work.

Your job: fetch the companies whose check interval has elapsed, use Firecrawl to
scrape their careers page, identify new listings, gate them, and update their tier
based on signal quality.

---

## Step 1 — Get due companies

Call `mcp__vps__get_due_catalogue_companies(limit=15)`.
If count = 0: nothing due, exit silently.

## Step 2 — For each company

1. Call `mcp__browser__navigate(url=company.careers_url)` to fetch the page in IXBrowser.
   Wait 3 seconds for page to load.
   Read via `mcp__cdp__cdp_eval("document.body.innerText.slice(0, 8000)")`.

   **OR** use Firecrawl if available: the raw text gives enough context.

2. Read the page content. Look for:
   - Individual job listing titles and links
   - Application deadlines
   - Whether they're still actively hiring for gig roles

3. For each NEW listing found (not already in jobs table by URL):
   - Gate it: is this actually a gig/task role?
   - If yes: call `mcp__vps__upsert_job(url=listing_url, title=..., company=...,
     job_type=..., source_url=company.careers_url, source="catalogue_poll")`

4. Update the company's tier based on what you found:
   - Found 3+ new gig listings: `update_catalogue_tier(id, tier=1, jobs_found=N, reason="active hiring")`
   - Found 1-2 new listings: `update_catalogue_tier(id, tier=2, jobs_found=N, reason="moderate activity")`
   - Found 0 new listings (page still active): `update_catalogue_tier(id, tier=3, jobs_found=0, reason="no new listings")`
   - Found 0 and page returns 404/error or company no longer posts gig work:
     `update_catalogue_tier(id, tier=0, jobs_found=0, reason="inactive or switched to FTE only")`

## Step 3 — Summary

`mcp__telegram__notify("Catalogue poll: checked N companies, N new listings found")`

---

## Tier definitions

| Tier | Check interval | When to use |
|---|---|---|
| 1 | Every 12h | Actively posting multiple gig listings |
| 2 | Every 48h | Posting occasionally, moderate signal |
| 3 | Every 168h (weekly) | Rarely posts, worth keeping an eye on |
| 0 | Archive (8760h) | No longer posting gig work |

---

## Rules

- Only process companies with `is_active = TRUE` in `discovered_platforms`.
- Never demote a Tier 1 company to Tier 0 in a single poll — go via Tier 2 or 3 first.
- If you can't reach a page (network error, timeout): leave the tier unchanged,
  update `last_checked_at` anyway, and note the error in `tier_reason`.
