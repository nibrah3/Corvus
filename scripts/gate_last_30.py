"""Final 30 jobs gate pass — zero unenriched after this."""
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

# Appen specific Lever job listings (Translation Evaluators — real gig roles)
keep([165227, 165226], "translation",    "Appen: Translation Evaluator RU+EN / KO+EN")

# Lionbridge worker-facing pages
keep([671],  "translation",   "Lionbridge main home (major translation/AI platform)")
keep([670],  "ai_training",   "Lionbridge AI Data Services")
keep([669],  "translation",   "Lionbridge Lever EU jobs page")
keep([668],  "ai_training",   "Lionbridge AI Opportunities platform")
keep([667],  "ai_training",   "Lionbridge AI careers")
keep([665],  "translation",   "Lionbridge: Join our Freelance Community")

# iMerit platforms
keep([664],  "data_annotation","iMerit on WelcomeToTheJungle")
keep([658],  "data_annotation","LinkedIn Kenya: iMerit Multimodal AI Evaluation Analyst")
keep([657],  "data_annotation","iMerit Scholars: Domain Experts")

# Job aggregators/platforms (AI training specific)
keep([663],  "ai_training",   "AIJobs.ai/training listing page")
keep([661],  "ai_training",   "Himalayas: Remote AI Training Jobs")

# Prolific worker/participant facing pages
keep([649],  "gpt",           "Prolific participants page (paid research tasks)")
keep([652],  "gpt",           "Prolific /ai page (participant-facing)")
keep([647],  "data_annotation","Prolific: Data generation and annotation")
keep([646],  "gpt",           "Prolific home: Work opportunity")

# TELUS and Toloka platforms
keep([625],  "search_rating", "TELUS International AI opportunities page")
keep([622],  "data_annotation","Toloka: Training data for AI platform")

# ── BLOCK ─────────────────────────────────────────────────────────────────────

# Blog posts and articles
block([673],  "blog_post", "Lionbridge blog: Remote Work 101")
block([655],  "blog_post", "Prolific blog: Prolific in 2025")
block([651],  "blog_post", "Prolific blog: What's New")
block([648],  "blog_post", "Prolific help: Taskflow AI Dataset Annotation")
block([616],  "blog_post", "Prolific blog: 5 alternatives to Scale AI")

# YouTube videos (not job listings)
block([660, 654, 628], "blog_post",
      "YouTube videos about AI training jobs/demo")

# LinkedIn posts (not job listings)
block([627],  "blog_post", "LinkedIn post: Earn Online with AI 12 platforms")

# Individual profile page (not a job)
block([626],  "vague",     "OpenTrain: individual annotator profile page")

# Lionbridge corporate hiring page (employees, not freelancers)
block([666],  "professional_job", "Lionbridge: Join our Corporate Team")

conn.commit()

# Final verification
cur2 = conn.cursor()
cur2.execute("""
    SELECT COUNT(*) FROM jobs
    WHERE (enriched IS FALSE OR enriched IS NULL)
    AND job_type IS NULL
    AND status NOT IN ('blocked','skipped','completed','failed','error','partial','applied')
""")
remaining = cur2.fetchone()[0]
conn.close()
print(f"\nLast pass: {total_kept} kept, {total_blocked} blocked")
print(f"Truly unenriched remaining: {remaining}")
