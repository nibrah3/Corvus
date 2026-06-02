"""Third direct Claude Code gate pass."""
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

# ── KEEP ────────────────────────────────────────────────────────────────────

# OneForma category pages — each is a real task category for workers
keep([4258], "translation",     "OneForma Translation tasks")
keep([4254, 4255], "data_annotation", "OneForma Annotation + Data Collection")
keep([4257], "transcription",   "OneForma Transcription tasks")
keep([4256], "search_rating",   "OneForma Judging/Rating tasks")
keep([4259, 4251, 4252], "other_gig", "OneForma all jobs + how it works + register")
keep([4261], "data_annotation", "DataAnnotation.tech worker signup form")
keep([4262], "data_annotation", "DataAnnotation.tech/law — legal domain annotation")

keep([4264, 4263], "ai_training", "Surge AI Careers + Workforce (RLHF platform)")
keep([3806],       "ai_training", "DataAnnotation.tech home — Work opportunity")
keep([3805],       "data_annotation", "Appen — Work opportunity")
keep([3808],       "other_gig",   "OneForma — Roles")
keep([3804],       "search_rating","TELUS International — Work opportunity (search quality)")
keep([3807, 4243], "customer_support", "Teleperformance careers + WFH page")
keep([3810],       "transcription", "SpeakWrite — Roles")
keep([4612, 4209], "microtask",    "Clickworker Store Check/Retail audit tasks")
keep([4061],       "virtual_assistant", "Postwork — Work opportunity")

# ── BLOCK ────────────────────────────────────────────────────────────────────

# Teleperformance locale / marketing pages
block([4242],  "vague", "Teleperformance Choose TP (marketing)")
block([4240],  "vague", "Teleperformance WFH Solution (B2B service)")
block([4250],  "vague", "Teleperformance main website (nav page)")
block([4244],  "vague", "Teleperformance For Fun Festival (employee event)")
block([4247],  "vague", "Teleperformance Jamaica (country page)")
block([4245],  "vague", "Teleperformance Belgium (country page)")
block([4246],  "vague", "Teleperformance Germany (country page)")
block([4241],  "vague", "Teleperformance Our Values page")
block([4249],  "vague", "Teleperformance Suriname (country page)")
block([4248],  "vague", "Teleperformance Netherlands (country page)")

# Concentrix locale page (missed earlier)
block([4237, 4235], "vague", "Concentrix IT/DE locale pages")

# TaskUs B2B service page
block([4222],  "vague", "TaskUs Autonomous Vehicles (B2B service)")

# Defined.ai — professional corporate roles + blog
block([4272],  "professional_job", "Defined.ai: AI/ML Sales Executive Enterprise")
block([4273],  "professional_job", "Defined.ai: Legal Counsel Tech")
block([4271],  "blog_post",        "Defined.ai blog post on employment scams")
block([4274],  "vague",            "JazzHR 'Powered by' — ATS footer page")

# Centific B2B page
block([4278],  "vague", "Centific Book a Demo (B2B marketing)")

# YC startup company profiles (not gig listings)
block([3802, 3801, 3800, 3799, 3798, 3797], "professional_job",
      "YC startup company pages (Enerjazz/Corgi/Chariot/Domu/Agave/Flint)")

# YC startup engineering roles
block([3796],  "professional_job", "Adaptional: Founding Engineer")
block([3795],  "professional_job", "RamAIn: Founding GTM Operations Lead")
block([3794],  "professional_job", "Substrate AI: Harness Engineer")
block([3809],  "professional_job", "Uber AI careers (engineering/research roles)")

conn.commit()
conn.close()
print(f"\nBatch 3 complete: {total_kept} kept, {total_blocked} blocked")
