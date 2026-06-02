"""Fourth direct gate pass — Testlio testing gigs + YC engineering roles + Reddit posts."""
import psycopg2, logging

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
DSN = "postgresql://corvus:corvus-local-password@127.0.0.1:5433/careerbridge"
conn = psycopg2.connect(DSN)
cur = conn.cursor()
total_kept = 0
total_blocked = 0

def keep(ids, job_type, label=""):
    global total_kept
    if not ids:
        return
    cur.execute("UPDATE jobs SET job_type=%s, enriched=TRUE WHERE id=ANY(%s)", (job_type, ids))
    logging.info("KEPT %d as %-22s %s", cur.rowcount, job_type, label)
    total_kept += cur.rowcount

def block(ids, reason, label=""):
    global total_blocked
    if not ids:
        return
    cur.execute(
        "UPDATE jobs SET status='blocked', quality_issue=%s, enriched=TRUE WHERE id=ANY(%s)",
        (reason, ids)
    )
    logging.info("BLOCKED %d [%s] %s", cur.rowcount, reason, label)
    total_blocked += cur.rowcount

# ── KEEP ──────────────────────────────────────────────────────────────────────

# Testlio REAL gig testing tasks — paid physical + remote testing projects
keep([3541, 3540, 3529], "testing",
     "Testlio Uber driver app testing (Spain/Ireland/Portugal)")
keep([3539, 3538, 3537], "testing",
     "Testlio Airport proximity testing projects")
keep([3536, 3535, 3534, 3533, 3532, 3531, 3530], "testing",
     "Testlio Freelance Software Tester (various regions/devices)")

# Outlier AI — legitimate gig AI tasks
keep([3767], "ai_training",  "Outlier AI: Coding Expert task")
keep([3572], "moderation",   "Outlier AI: AI Content Moderator Tier 1")

# Surge AI generalist annotation role
keep([3762], "ai_training",  "SurgeHQ: Generative AI Generalist")

# iMerit data annotation jobs (LinkedIn listing for a legit annotation company)
keep([3619], "data_annotation", "iMerit Technology jobs on LinkedIn")

# ── BLOCK ─────────────────────────────────────────────────────────────────────

# YC/startup engineering, management, and professional roles — all professional
block([3793, 3792, 3791, 3790, 3789, 3788, 3787, 3786, 3785, 3784,
       3783, 3782, 3781, 3780, 3779, 3778, 3777, 3776, 3775, 3774,
       3773, 3772, 3771, 3770, 3769, 3768],
      "professional_job",
      "YC/startup engineering roles (Platform Eng, FDE, Backend, Growth Eng, etc.)")

# Testlio placeholder "Future Roles" — not real job listings
block([3543, 3542], "vague", "Testlio Future Roles placeholders (QA Tester/Analyst)")

# Reddit discussion posts — not job listings
block([3596, 3573, 3564], "blog_post",
      "Reddit posts about AI training jobs (discussion threads, not listings)")

# Anthropic professional research roles
block([3265, 3152], "professional_job",
      "Anthropic: Research Manager + Fellows Program (academic/professional)")

conn.commit()
conn.close()
print(f"\nBatch 4 complete: {total_kept} kept, {total_blocked} blocked")
