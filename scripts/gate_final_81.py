"""Final gate pass — 81 remaining jobs."""
import psycopg2, logging

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
DSN = "postgresql://corvus:corvus-local-password@127.0.0.1:5433/careerbridge"
conn = psycopg2.connect(DSN)
cur = conn.cursor()
total_kept = 0; total_blocked = 0

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
keep([584], "ai_training",    "DataAnnotation.tech home")
keep([585], "ai_training",    "DataAnnotation.tech generalist AI training page")
keep([588], "data_annotation","Appen data annotation services page")
keep([592], "ai_training",    "DataAnnotation language directory")
keep([594], "ai_training",    "OpenTrain AI: Become a Freelancer")
keep([598], "ai_training",    "LXT.ai: Careers & Jobs in AI")
keep([600], "ai_training",    "RWS TrainAI Community")
keep([605], "ai_training",    "Mindrift AI: AI Training Jobs platform")
keep([612], "ai_training",    "Outlier.ai home")
keep([615], "ai_training",    "DataAnnotation Specialist via Vaia Talents")
keep([619], "ai_training",    "Remotasks US acquisition project page")

# ── BLOCK ─────────────────────────────────────────────────────────────────────

# DataAnnotation blog posts (article URLs, not job listings)
block([586,587,589,590,591,593], "blog_post",
      "DataAnnotation.tech blog posts (legit/tips/requirements/what-is)")

# Aggregator search pages
block([595], "aggregator_search_page", "OperationsArmy: data annotation jobs search")
block([596], "aggregator_search_page", "Rex Zone: AI data labeling jobs search")
block([608], "aggregator_search_page", "Upwork: content moderator freelance jobs search")

# Blog articles / listicles about AI training companies
block([599], "blog_post", "ReworkTimes: Best Remote Jobs for AI Training")
block([602], "blog_post", "HeroHunt: Ultimate AI Data Labeling Industry Overview")
block([620], "blog_post", "Ludditus: questionable industry of AI training")
block([621], "blog_post", "RatRaceRebellion: 10 Companies Hiring Remote AI Training")

# Reddit/social discussion threads
block([606], "blog_post", "Reddit: AI Training legit jobs? (r/remotework)")
block([613], "blog_post", "Reddit: Any other sites like Outlier? (r/outlier_ai)")
block([614], "blog_post", "Facebook group post about AI training platforms")

# Scale AI full careers page (not a specific gig listing) + Senior ML Engineer
block([601], "vague",           "Scale.com/careers (full corporate careers homepage)")
block([618], "professional_job","LinkedIn Scale AI: Senior ML Engineer Model Evaluation")

# Revelo — software developer job marketplace (not gig annotation work)
block([603], "professional_job","Revelo: software dev marketplace")

# Bulk-block all remaining DataAnnotation blog posts not already covered
cur.execute("""
    UPDATE jobs SET status='blocked', quality_issue='blog_post', enriched=TRUE
    WHERE (enriched IS FALSE OR enriched IS NULL)
    AND job_type IS NULL
    AND status NOT IN ('blocked','skipped','completed','failed','error','partial','applied')
    AND url LIKE '%%dataannotation.tech/blog%%'
""")
logging.info("BLOCKED %d remaining DataAnnotation blog posts", cur.rowcount)
total_blocked += cur.rowcount

# Bulk-block all remaining Reddit discussion posts
cur.execute("""
    UPDATE jobs SET status='blocked', quality_issue='blog_post', enriched=TRUE
    WHERE (enriched IS FALSE OR enriched IS NULL)
    AND job_type IS NULL
    AND status NOT IN ('blocked','skipped','completed','failed','error','partial','applied')
    AND url LIKE '%%reddit.com%%'
""")
logging.info("BLOCKED %d remaining Reddit posts", cur.rowcount)
total_blocked += cur.rowcount

# Bulk-block all remaining Facebook/Instagram posts
cur.execute("""
    UPDATE jobs SET status='blocked', quality_issue='blog_post', enriched=TRUE
    WHERE (enriched IS FALSE OR enriched IS NULL)
    AND job_type IS NULL
    AND status NOT IN ('blocked','skipped','completed','failed','error','partial','applied')
    AND (url LIKE '%%facebook.com%%' OR url LIKE '%%instagram.com%%')
""")
logging.info("BLOCKED %d remaining social media posts", cur.rowcount)
total_blocked += cur.rowcount

conn.commit()

# Final check
cur2 = conn.cursor()
cur2.execute("""
    SELECT COUNT(*) FROM jobs
    WHERE (enriched IS FALSE OR enriched IS NULL)
    AND job_type IS NULL
    AND status NOT IN ('blocked','skipped','completed','failed','error','partial','applied')
""")
remaining = cur2.fetchone()[0]

conn.close()
print(f"\nFinal pass: {total_kept} kept, {total_blocked} blocked")
print(f"Truly unenriched remaining: {remaining}")
