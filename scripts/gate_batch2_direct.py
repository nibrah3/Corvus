"""Second direct Claude Code gate pass — career sub-pages batch."""
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

# ── KEEP: legitimate gig worker pages ───────────────────────────────────────

keep([4549],  "microtask",      "Microworkers — microtask platform")
keep([4059],  "microtask",      "Amazon MTurk — mechanical turk tasks")
keep([4203,4204], "microtask",  "Clickworker worker signup/login pages")

keep([4615],  "data_annotation","DataAnnotation.tech/finance — AI annotation (finance domain)")
keep([4207],  "data_annotation","Clickworker AI Training Data page")
keep([4210],  "data_annotation","Clickworker Tagging/Categorization Services")
keep([4265],  "data_annotation","Hive (thehive.ai) — AI data annotation platform")
keep([4269,4270], "data_annotation","Defined.ai careers + apply page")

keep([4275],  "ai_training",    "Centific Expert Network (annotation/AI training)")
keep([4276],  "ai_training",    "Centific Workday open positions")
keep([4253],  "ai_training",    "OneForma: Native Speaker Audio Discussion Study")

keep([4260],  "transcription",  "SpeakWrite — transcription platform")

keep([4266,4268], "translation","Welocalize Lever jobs + community hiring")

keep([4239],  "customer_support","Teleperformance Job Opportunities (BPO)")

keep([4211],  "testing",        "Clickworker Testing Services")
keep([4208],  "gpt",            "Clickworker Surveys")
keep([4214],  "gpt",            "Clickworker Research/data services")
keep([4060],  "gpt",            "CloudResearch — paid research studies")

keep([4212],  "virtual_assistant","Clickworker List Building (data entry tasks)")

# ── BLOCK: service sub-pages, language locale pages, non-job content ─────────

# Lionbridge / Concentrix / Welocalize locale subpages
block([4646],  "vague", "Lionbridge IT (Italian locale page)")
block([4238,4232,4234,4236,4231,4233], "vague",
      "Concentrix locale pages (PL/NL/FR/ID/AR/EN root)")
block([4229,4228,4230,4227], "vague",
      "Concentrix About Us / Our Culture / Contact / Job Search nav pages")
block([4267],  "vague", "Welocalize About > Careers (nav page, kept real lever link)")

# TaskUs service/product pages (B2B, not worker opportunities)
block([4225],  "vague", "TaskUs Trust & Safety services page (B2B)")
block([4216],  "vague", "TaskUs About Us")
block([4219],  "vague", "TaskUs Deployment & AI Operations (B2B service)")
block([4224],  "vague", "TaskUs Agentic AI (B2B service)")
block([4217],  "vague", "TaskUs Locations page")
block([4218],  "vague", "TaskUs AI Safety & Alignment (B2B service)")
block([4221],  "vague", "TaskUs Data Feedback & Evaluations (B2B service)")
block([4220],  "vague", "TaskUs Japanese AI Operations (B2B)")
block([4226],  "vague", "TaskUs Wellness & Resiliency (B2B)")
block([4223],  "vague", "TaskUs Robotics (B2B service)")
block([4215],  "vague", "TaskUs For Job Seekers (contact/CTA page, not listing)")

# Clickworker service/product pages (B2B, not worker signup)
block([4598],  "vague", "Clickworker For Customers (B2B page)")
block([4213],  "vague", "Clickworker SEO Services (B2B service)")

# YC internship / professional role
block([4315],  "professional_job", "Text Blaze No AI Summer Internship (YC internship)")

# Centific main careers nav page (kept the Workday listing above)
block([4277],  "vague", "Centific Careers nav page (kept Workday listing)")

conn.commit()
conn.close()
print(f"\nBatch 2 complete: {total_kept} kept, {total_blocked} blocked")
