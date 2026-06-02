"""Fifth direct gate pass — Prolific AI Training, blogs, test entries, Scale AI corporate."""
import psycopg2, logging

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
DSN = "postgresql://corvus:corvus-local-password@127.0.0.1:5433/careerbridge"
conn = psycopg2.connect(DSN)
cur = conn.cursor()
total_kept = 0
total_blocked = 0

def keep(ids, job_type, label=""):
    global total_kept
    if not ids: return
    cur.execute("UPDATE jobs SET job_type=%s, enriched=TRUE WHERE id=ANY(%s)", (job_type, ids))
    logging.info("KEPT %d as %-22s %s", cur.rowcount, job_type, label)
    total_kept += cur.rowcount

def block(ids, reason, label=""):
    global total_blocked
    if not ids: return
    cur.execute(
        "UPDATE jobs SET status='blocked', quality_issue=%s, enriched=TRUE WHERE id=ANY(%s)",
        (reason, ids)
    )
    logging.info("BLOCKED %d [%s] %s", cur.rowcount, reason, label)
    total_blocked += cur.rowcount

# ── KEEP ──────────────────────────────────────────────────────────────────────

# Prolific AI Training Specialist roles (task-based, various regions)
keep([801,800,799,798,797,796,795,794], "ai_training",
     "Prolific AI Training Specialist (multiple regions)")
keep([793, 792], "ai_training", "Prolific AI Training Research Scientist roles")

# Remotasks AI annotation/training tasks
keep([812], "ai_training",    "Remotasks: Video Content Description for AI Training")
keep([811], "ai_training",    "Remotasks: AI Training for Igbo Writers")

# Gig platform homepages and worker signup pages
keep([2576], "ai_training",   "Clickworker: AI Training Participant signup")
keep([2169], "data_annotation","Clickworker: Data Services home")
keep([2431], "data_annotation","iMerit: Join iMerit careers page")
keep([890],  "data_annotation","iMerit Scholars: single job page")
keep([2138], "ai_training",   "OpenTrain AI: AI trainers & data labelers platform")
keep([1785], "ai_training",   "WeWorkRemotely: Lionbridge AI remote jobs")
keep([1125], "ai_training",   "Lionbridge Careers search page")
keep([1081], "search_rating", "TELUS International AI homepage")
keep([1076], "other_gig",     "Stellar AI: flexible work platform")
keep([1058], "ai_training",   "Web Spiders: RLHF & Expert Labelling platform")
keep([1115], "ai_training",   "Braintrust: Biology AI Training (task-based annotation)")

# ── BLOCK ─────────────────────────────────────────────────────────────────────

# Anthropic Fellows Programs — competitive academic research fellowships, not gig tasks
block([3151,3150,3149,3148,3147], "professional_job",
      "Anthropic Fellows Programs (RL/ML Systems/AI Security/AI Safety — academic)")

# Scale AI corporate/management roles — not gig annotation tasks
block([2589,2588,2587,2584,2583,2582,2581], "professional_job",
      "Scale AI: corporate roles (Recruiter/Ops Manager/Legal/Strategy)")
block([2579], "professional_job", "Surge AI: RL Environments Architect (ML engineering)")

# Test entries — synthetic smoke test records
block([2942, 2343], "test_entry",
      "Smoke test / synthetic test job entries (example.com, test-job-12345.com)")

# Blog posts, Reddit discussions, social media posts — not job listings
block([2176, 2143, 1306, 1106, 1538], "blog_post",
      "Reddit discussion threads about AI training jobs")
block([882],  "blog_post", "Prolific help article (how AI Task Builder works)")
block([856],  "blog_post", "Instagram reel about AI training income")
block([852],  "blog_post", "Facebook post about Remotasks tasks")
block([844],  "blog_post", "AITrainingJobs.it article (Best companies 2026)")
block([843],  "blog_post", "AlgorithmWatch: Scams and Shadow Workers article")
block([820],  "blog_post", "DataAnnotation blog: Is DataAnnotation a Scam?")

# Aggregator search pages
block([2153], "aggregator_search_page",
      "Upwork /freelance-jobs/data-annotation (search results page)")

conn.commit()
conn.close()
print(f"\nBatch 5 complete: {total_kept} kept, {total_blocked} blocked")
