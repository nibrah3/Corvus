"""
Direct Claude Code gate pass — classifies jobs using my reasoning, no external API.
This processes the remaining unenriched jobs directly via SQL without any LLM calls.
"""
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
    cur.execute(
        "UPDATE jobs SET job_type=%s, enriched=TRUE WHERE id=ANY(%s)",
        (job_type, ids)
    )
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

# ── KEEP: legitimate gig platforms ──────────────────────────────────────────

keep([158513],           "gpt",              "Respondent.io — paid research studies")
keep([121166],           "gpt",              "Pawns.app — passive income/bandwidth sharing")
keep([26639],            "gpt",              "GetGrass — bandwidth sharing GPT")
keep([26637],            "gpt",              "Grindbux — GPT/beermoney")
keep([8968],             "gpt",              "Honey — cashback browser extension")
keep([8969],             "gpt",              "Coupert — cashback extension")
keep([5537],             "gpt",              "Field Agent — mystery shopping/research tasks")
keep([118476, 12633],    "virtual_assistant", "Postwork/Postwork.io — VA gig platform")

keep([35097],            "data_annotation",  "Remotasks — Scale AI annotation platform")
keep([36589],            "ai_training",      "BeBee: AI Data Labeling RLHF QA Specialist")
keep([4635],             "ai_training",      "Centific/Multilingual AI")

keep([35109, 5527],      "transcription",    "Escribers + TranscribeMe")
keep([15718, 5998, 5763], "translation",     "Bilingual Global (3 entries)")
keep([4651],             "translation",      "Lionbridge Machine Translation page")

keep([35116],            "customer_support", "Simplrflex — customer service gig")
keep([35113],            "customer_support", "TTEC — BPO customer service")
keep([35115],            "customer_support", "Working Solutions — virtual call center")
keep([35114],            "customer_support", "Concentrix — BPO")
keep([5768],             "customer_support", "5CA — customer support BPO")

keep([87324],            "testing",          "Testlio: Uber Driver for Testing the Uber App")
keep([5770],             "testing",          "Test.io — crowdtesting platform")

keep([5765],             "other_gig",        "Freelancer.com — freelance marketplace")
keep([93524],            "other_gig",        "LinkX — gig platform from reddit")
keep([63634],            "other_gig",        "MindyCore — gig platform from reddit")
keep([37804, 30276],     "other_gig",        "Tokportal — gig platform from reddit")
keep([26638],            "other_gig",        "SimpleBits — gig platform from reddit")

# ── BLOCK: professional corporate roles and vague pages ─────────────────────

block([134156],          "professional_job", "Gartner Peer Insights — corporate B2B reviews")
block([122848],          "professional_job", "TinyPilot — hardware KVM company")
block([35110],           "professional_job", "Epiq — legal services company")
block([35117],           "vague",            "Amazon jobs homepage — not a specific listing")
block([5764],            "professional_job", "Ascension Health — healthcare corporate")
block([101952],          "professional_job", "Belle Muse — fashion/beauty company careers")

# Scale AI and Anthropic corporate/engineering roles
block([95136],           "professional_job", "Testlio: Manager, Freelance Recruiting (HR role)")
block([71551],           "professional_job", "Scale AI: Business Development Representative")
block([53303],           "professional_job", "Testlio: Corporate Program Manager")
block([31782],           "vague",            "Testlio: Quality Engineer Future Roles (placeholder)")
block([31700],           "professional_job", "Scale AI: Applied AI Engineer GovSec")
block([31699],           "professional_job", "Scale AI: Applied AI Engineer Enterprise")
block([21354],           "professional_job", "Anthropic: Research Engineer Red Team Cyber")
block([21353],           "professional_job", "Anthropic: Research Engineer Red Team Autonomy")
block([58445],           "professional_job", "Scale AI: AI Deployment Strategist Enterprise")

# Lionbridge localized language pages (not job listings — just translated career homepages)
block([4644, 4643, 4645], "vague",           "Lionbridge ES/DE/FR language subpages (not jobs)")
block([4611],            "vague",            "Clickworker eCommerce services page (not a job)")

conn.commit()
conn.close()

print(f"\nDirect gate complete: {total_kept} kept, {total_blocked} blocked")
