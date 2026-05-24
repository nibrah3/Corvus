"""
CareerBridge Telegram Bot — Primary UI Entry Point
===================================================
Pushes job discoveries, schools, and company career-page finds to users.
Admin-only commands are restricted to TELEGRAM_ADMIN_CHAT_ID.
Regular users: read-only browsing, job alerts, school listings.
"""
import os, sys, json, logging, asyncio, textwrap
from datetime import datetime, timezone
from functools import wraps
sys.path.insert(0, os.path.dirname(__file__))

# ── Load .env ─────────────────────────────────────────────────────────────────
for line in open(os.path.join(os.path.dirname(__file__), "..", ".env")).read().splitlines():
    if "=" in line and not line.startswith("#"):
        k, _, v = line.partition("=")
        os.environ[k.strip()] = v.strip()

from telegram import (
    Update, InlineKeyboardButton, InlineKeyboardMarkup,
    WebAppInfo, BotCommand, MenuButtonWebApp
)
from telegram.ext import (
    Application, CommandHandler, CallbackQueryHandler,
    MessageHandler, filters, ContextTypes, JobQueue
)
from telegram.constants import ParseMode

logging.basicConfig(
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    level=logging.INFO,
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler(os.path.join(os.path.dirname(__file__), "..", "logs", "telegram_bot.log"))
    ]
)
log = logging.getLogger("corvus_bot")

# ── Config ─────────────────────────────────────────────────────────────────────
BOT_TOKEN       = os.environ["TELEGRAM_BOT_TOKEN"]
ADMIN_CHAT_ID   = int(os.environ["TELEGRAM_ADMIN_CHAT_ID"])
WEBAPP_URL      = "https://nibrah3.github.io/Corvus/"   # GitHub Pages
PAGE_SIZE       = 5                                      # jobs per page
POLL_INTERVAL   = 300                                    # 5 minutes

# ── DB helper ─────────────────────────────────────────────────────────────────
try:
    import psycopg2, psycopg2.extras
    _DB_URL = os.environ.get("VPS_PG_DSN", "postgresql://corvus:corvus-local-password@127.0.0.1:5433/careerbridge")
    def get_db():
        return psycopg2.connect(_DB_URL, connect_timeout=10)
    HAS_DB = True
except Exception:
    HAS_DB = False
    log.warning("psycopg2 unavailable — DB features disabled")

def db_query(sql: str, params=(), many=False):
    if not HAS_DB:
        return [] if many else None
    try:
        with get_db() as conn:
            with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
                cur.execute(sql, params)
                return (cur.fetchall() if many else cur.fetchone()) or ([] if many else None)
    except Exception as e:
        log.error("DB error: %s", e)
        return [] if many else None

# ── Permission decorator ───────────────────────────────────────────────────────
def admin_only(func):
    @wraps(func)
    async def wrapper(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
        uid = update.effective_user.id if update.effective_user else None
        if uid != ADMIN_CHAT_ID:
            await update.effective_message.reply_text(
                "⛔ Admin access required for this command."
            )
            return
        return await func(update, ctx)
    return wrapper

# ── Keyboards ─────────────────────────────────────────────────────────────────
def main_menu_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton("💼 Browse Jobs",       callback_data="jobs:0:all"),
            InlineKeyboardButton("🎓 Schools",           callback_data="schools:0:best"),
        ],
        [
            InlineKeyboardButton("🏢 Companies",         callback_data="companies:0"),
            InlineKeyboardButton("🔍 Latest Finds",      callback_data="discover:0"),
        ],
        [
            InlineKeyboardButton("📊 Open Full App",
                                 web_app=WebAppInfo(url=WEBAPP_URL)),
        ],
    ])

def job_filter_kb(sector: str = "all") -> InlineKeyboardMarkup:
    sectors = [("All", "all"), ("Gig", "gig"), ("Annotation", "annotation"), ("Education", "education")]
    rows = [[
        InlineKeyboardButton(
            ("✅ " if s == sector else "") + label,
            callback_data=f"jobs:0:{s}"
        ) for label, s in sectors
    ]]
    return InlineKeyboardMarkup(rows)

def pager_kb(prefix: str, page: int, total: int, extra: str = "") -> InlineKeyboardMarkup:
    btns = []
    if page > 0:
        btns.append(InlineKeyboardButton("◀ Prev", callback_data=f"{prefix}:{page-1}:{extra}"))
    if (page + 1) * PAGE_SIZE < total:
        btns.append(InlineKeyboardButton("Next ▶", callback_data=f"{prefix}:{page+1}:{extra}"))
    rows = [btns] if btns else []
    rows.append([InlineKeyboardButton("🏠 Menu", callback_data="menu")])
    return InlineKeyboardMarkup(rows)

def school_filter_kb(active: str = "all") -> InlineKeyboardMarkup:
    filters_list = [
        ("🏆 Best Match",          "best"),
        ("All",                   "all"),
        ("Community College",     "community"),
        ("No ID Verification",    "noid"),
        ("Monthly Enrollment",    "monthly"),
        ("Instant Acceptance",    "instant"),
        ("No Transcripts",        "notranscript"),
        ("Monthly Refund",        "refund"),
    ]
    rows = []
    row = []
    for label, key in filters_list:
        row.append(InlineKeyboardButton(
            ("✅ " if key == active else "") + label,
            callback_data=f"schools:0:{key}"
        ))
        if len(row) == 2:
            rows.append(row); row = []
    if row:
        rows.append(row)
    rows.append([InlineKeyboardButton("🏠 Menu", callback_data="menu")])
    return InlineKeyboardMarkup(rows)

# ── Formatters ─────────────────────────────────────────────────────────────────
def fmt_job(job: dict) -> str:
    title   = job.get("title", "Unknown")[:60]
    company = job.get("company", "Unknown")[:40]
    url     = job.get("url", "")
    sector  = (job.get("sector") or "gig").upper()
    desc    = textwrap.shorten(job.get("description") or "", width=120, placeholder="…")
    posted  = ""
    if job.get("posted_at"):
        try:
            dt = job["posted_at"]
            posted = f"\n📅 {dt.strftime('%b %d, %Y') if hasattr(dt, 'strftime') else str(dt)[:10]}"
        except Exception:
            pass
    line1 = f"💼 *{_esc(title)}*"
    line2 = f"🏢 {_esc(company)}  •  `{sector}`{posted}"
    line3 = f"_{_esc(desc)}_" if desc else ""
    link  = f"[🔗 View Job]({url})" if url else ""
    return "\n".join(filter(None, [line1, line2, line3, link]))

def fmt_school(s: dict) -> str:
    name    = s.get("name", "Unknown")[:80]
    url     = s.get("enrollment_url") or s.get("url", "")
    filters = s.get("filters") or []
    badge   = " • ".join(filters[:3]) if filters else "General"
    desc    = textwrap.shorten(s.get("evidence") or s.get("description") or "", width=120, placeholder="…")
    parts = [
        f"🎓 *{_esc(name)}*",
        f"📋 {_esc(badge)}",
    ]
    if desc:
        parts.append(f"_{_esc(desc)}_")
    if url:
        parts.append(f"[🌐 Enrollment Page]({url})")
    return "\n".join(parts)

def fmt_company(c: dict) -> str:
    name = c.get("company", "Unknown")[:60]
    url  = c.get("careers_url", "")
    src  = c.get("source", "")
    last = c.get("last_checked")
    parts = [f"🏢 *{_esc(name)}*"]
    if url:
        parts.append(f"[🔗 Careers Page]({url})")
    if src:
        parts.append(f"📡 Source: `{_esc(src)}`")
    return "\n".join(parts)

def _esc(text: str) -> str:
    """Escape MarkdownV2 special chars."""
    if not text:
        return ""
    for ch in r"\_*[]()~`>#+-=|{}.!":
        text = text.replace(ch, f"\\{ch}")
    return text

# ── Handlers ───────────────────────────────────────────────────────────────────
async def cmd_start(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    name = update.effective_user.first_name or "there"
    is_admin = update.effective_user.id == ADMIN_CHAT_ID
    admin_badge = " _(admin)_" if is_admin else ""
    text = (
        f"👋 Hey *{_esc(name)}*{admin_badge}\\!\n\n"
        "*CareerBridge* finds remote jobs, schools, and company career pages "
        "— and pushes them straight to you\\.\n\n"
        "Use the buttons below to browse, or open the full app\\.\n"
        "I'll notify you the moment something new drops\\."
    )
    await update.message.reply_text(
        text, parse_mode=ParseMode.MARKDOWN_V2,
        reply_markup=main_menu_kb()
    )

async def cmd_menu(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "📱 *CareerBridge Hub*", parse_mode=ParseMode.MARKDOWN_V2,
        reply_markup=main_menu_kb()
    )

async def cmd_jobs(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    await _send_jobs(update, ctx, page=0, sector="all")

async def cmd_schools(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    await _send_schools(update, ctx, page=0, filt="best")

async def cmd_discover(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    await _send_discover(update, ctx, page=0)

async def cmd_stats(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    jobs      = db_query("SELECT COUNT(*) cnt FROM jobs", many=False)
    companies = db_query("SELECT COUNT(*) cnt FROM discovered_platforms", many=False)
    schools   = db_query("SELECT COUNT(*) cnt FROM schools", many=False)
    channels  = db_query("SELECT COUNT(*) cnt FROM discovery_channels WHERE active=true", many=False)
    j = (jobs or {}).get("cnt", "?")
    c = (companies or {}).get("cnt", "?")
    s = (schools or {}).get("cnt", "?")
    ch = (channels or {}).get("cnt", "?")
    await update.effective_message.reply_text(
        f"📊 *System Stats*\n\n"
        f"💼 Jobs indexed: `{j}`\n"
        f"🏢 Companies tracked: `{c}`\n"
        f"🎓 Schools listed: `{s}`\n"
        f"📡 Active channels: `{ch}`",
        parse_mode=ParseMode.MARKDOWN_V2,
        reply_markup=InlineKeyboardMarkup([[
            InlineKeyboardButton("🏠 Menu", callback_data="menu")
        ]])
    )

# ── Admin commands ─────────────────────────────────────────────────────────────
@admin_only
async def cmd_admin(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "🛠 *Admin Panel*",
        parse_mode=ParseMode.MARKDOWN_V2,
        reply_markup=InlineKeyboardMarkup([
            [
                InlineKeyboardButton("📊 Full Stats",   callback_data="admin:stats"),
                InlineKeyboardButton("📡 Channels",     callback_data="admin:channels"),
            ],
            [
                InlineKeyboardButton("🔄 Force Scan",   callback_data="admin:scan"),
                InlineKeyboardButton("🗑 Clear Dupes",  callback_data="admin:dedup"),
            ],
            [
                InlineKeyboardButton("🏠 Menu",         callback_data="menu"),
            ]
        ])
    )

@admin_only
async def cmd_broadcast(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    msg = " ".join(ctx.args) if ctx.args else ""
    if not msg:
        await update.message.reply_text("Usage: /broadcast <message>"); return
    await update.message.reply_text(f"📣 Broadcast sent: {msg[:100]}")

# ── Callback router ────────────────────────────────────────────────────────────
async def on_callback(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    data  = query.data or ""
    parts = data.split(":")

    if data == "menu":
        await query.edit_message_text(
            "📱 *CareerBridge Hub*",
            parse_mode=ParseMode.MARKDOWN_V2,
            reply_markup=main_menu_kb()
        )

    elif parts[0] == "jobs":
        page   = int(parts[1]) if len(parts) > 1 else 0
        sector = parts[2] if len(parts) > 2 else "all"
        await _send_jobs(update, ctx, page, sector, edit=True)

    elif parts[0] == "schools":
        page = int(parts[1]) if len(parts) > 1 else 0
        filt = parts[2] if len(parts) > 2 else "all"
        await _send_schools(update, ctx, page, filt, edit=True)

    elif parts[0] == "companies":
        page = int(parts[1]) if len(parts) > 1 else 0
        await _send_companies(update, ctx, page, edit=True)

    elif parts[0] == "discover":
        page = int(parts[1]) if len(parts) > 1 else 0
        await _send_discover(update, ctx, page, edit=True)

    elif parts[0] == "admin":
        await _handle_admin_cb(query, parts[1] if len(parts) > 1 else "")

# ── Page senders ───────────────────────────────────────────────────────────────
async def _send_jobs(update: Update, ctx, page: int, sector: str,
                     edit: bool = False):
    where = "" if sector == "all" else "WHERE sector = %s"
    params = (sector,) if sector != "all" else ()
    total_row = db_query(
        f"SELECT COUNT(*) cnt FROM jobs {where}", params, many=False
    )
    total = (total_row or {}).get("cnt", 0)
    rows  = db_query(
        f"SELECT title, company, url, sector, description, posted_at FROM jobs "
        f"{where} ORDER BY id DESC LIMIT %s OFFSET %s",
        params + (PAGE_SIZE, page * PAGE_SIZE), many=True
    )
    if not rows:
        text = "No jobs found for this filter\\."
    else:
        parts = [f"💼 *Jobs* \\— page {page+1} of {max(1,(total+PAGE_SIZE-1)//PAGE_SIZE)}"
                 f"  \\({total} total\\)\n"]
        parts += [fmt_job(r) for r in rows]
        text = "\n\n─────\n".join(parts)

    kb = InlineKeyboardMarkup([
        list(filter(None, [
            InlineKeyboardButton("◀", callback_data=f"jobs:{page-1}:{sector}") if page > 0 else None,
            InlineKeyboardButton("Next ▶", callback_data=f"jobs:{page+1}:{sector}")
            if (page + 1) * PAGE_SIZE < total else None,
        ])),
        [
            InlineKeyboardButton("All",        callback_data="jobs:0:all"),
            InlineKeyboardButton("Gig",        callback_data="jobs:0:gig"),
            InlineKeyboardButton("Annotation", callback_data="jobs:0:annotation"),
        ],
        [
            InlineKeyboardButton("Education",  callback_data="jobs:0:education"),
            InlineKeyboardButton("🏠 Menu",    callback_data="menu"),
        ],
    ])
    await _reply(update, text, kb, edit)

async def _send_schools(update: Update, ctx, page: int, filt: str,
                        edit: bool = False):
    SCORE_EXPR = (
        "(no_id_verification::int + monthly_enrollment::int + instant_acceptance::int + "
        "no_transcript_required::int + monthly_refund::int + community_college::int)"
    )
    filter_map = {
        "community":    "type ILIKE '%community%'",
        "noid":         "no_id_verification = true",
        "monthly":      "monthly_enrollment = true",
        "instant":      "instant_acceptance = true",
        "notranscript": "no_transcript_required = true",
        "refund":       "monthly_refund = true",
        "best":         f"{SCORE_EXPR} >= 4",  # 4+ criteria = "best match"
    }
    where_clause = f"WHERE {filter_map[filt]}" if filt in filter_map else ""
    total_row = db_query(
        f"SELECT COUNT(*) cnt FROM schools {where_clause}", many=False
    )
    total = (total_row or {}).get("cnt", 0)
    rows  = db_query(
        f"SELECT name, url, enrollment_url, type, evidence, "
        f"no_id_verification, monthly_enrollment, instant_acceptance, "
        f"no_transcript_required, monthly_refund, community_college, "
        f"{SCORE_EXPR} AS criteria_score "
        f"FROM schools {where_clause} "
        f"ORDER BY {SCORE_EXPR} DESC, name LIMIT %s OFFSET %s",
        (PAGE_SIZE, page * PAGE_SIZE), many=True
    )
    if not rows:
        text = "No schools match this filter\\. We're still scraping\\!"
    else:
        header = f"🎓 *Schools* \\— page {page+1}  \\({total} total\\)"
        if filt == "best":
            header = f"🏆 *Best Match Schools* \\— {total} meeting 4\\+ criteria"
        parts = [header + "\n"]
        for r in rows:
            flags = []
            score = r.get("criteria_score", 0)
            if r.get("community_college"):         flags.append("🏫 Community")
            if r.get("no_id_verification"):        flags.append("✅ No ID")
            if r.get("monthly_enrollment"):        flags.append("📅 Monthly")
            if r.get("instant_acceptance"):        flags.append("⚡ Instant")
            if r.get("no_transcript_required"):    flags.append("📄 No Transcript")
            if r.get("monthly_refund"):            flags.append("💰 Refund")
            star = "🏆 " if score == 6 else ("⭐ " if score >= 4 else "")
            rd = dict(r)
            rd["name"]    = f"{star}{rd.get('name','')}"
            rd["filters"] = flags
            parts.append(fmt_school(rd))
        text = "\n\n─────\n".join(parts)

    nav = []
    if page > 0:
        nav.append(InlineKeyboardButton("◀", callback_data=f"schools:{page-1}:{filt}"))
    if (page+1)*PAGE_SIZE < total:
        nav.append(InlineKeyboardButton("Next ▶", callback_data=f"schools:{page+1}:{filt}"))

    kb = InlineKeyboardMarkup([
        nav,
        [
            InlineKeyboardButton("🏆 Best Match", callback_data="schools:0:best"),
            InlineKeyboardButton("All",            callback_data="schools:0:all"),
        ],
        [
            InlineKeyboardButton("Community",      callback_data="schools:0:community"),
            InlineKeyboardButton("No ID",          callback_data="schools:0:noid"),
            InlineKeyboardButton("Monthly",        callback_data="schools:0:monthly"),
        ],
        [
            InlineKeyboardButton("Instant",        callback_data="schools:0:instant"),
            InlineKeyboardButton("No Transcript",  callback_data="schools:0:notranscript"),
            InlineKeyboardButton("🏠 Menu",        callback_data="menu"),
        ],
    ])
    await _reply(update, text, kb, edit)

async def _send_companies(update: Update, ctx, page: int, edit: bool = False):
    total_row = db_query("SELECT COUNT(*) cnt FROM discovered_platforms", many=False)
    total     = (total_row or {}).get("cnt", 0)
    rows      = db_query(
        "SELECT company, careers_url, source, last_checked "
        "FROM discovered_platforms ORDER BY id DESC LIMIT %s OFFSET %s",
        (PAGE_SIZE, page * PAGE_SIZE), many=True
    )
    if not rows:
        text = "No companies tracked yet\\."
    else:
        parts = [f"🏢 *Companies* \\— page {page+1}  \\({total} tracked\\)\n"]
        parts += [fmt_company(r) for r in rows]
        text = "\n\n─────\n".join(parts)

    nav = []
    if page > 0:
        nav.append(InlineKeyboardButton("◀", callback_data=f"companies:{page-1}"))
    if (page+1)*PAGE_SIZE < total:
        nav.append(InlineKeyboardButton("Next ▶", callback_data=f"companies:{page+1}"))
    kb = InlineKeyboardMarkup([nav, [InlineKeyboardButton("🏠 Menu", callback_data="menu")]])
    await _reply(update, text, kb, edit)

async def _send_discover(update: Update, ctx, page: int, edit: bool = False):
    rows = db_query(
        "SELECT title, company, url, sector, created_at FROM jobs "
        "ORDER BY id DESC LIMIT %s OFFSET %s",
        (PAGE_SIZE, page * PAGE_SIZE), many=True
    )
    total_row = db_query("SELECT COUNT(*) cnt FROM jobs", many=False)
    total = (total_row or {}).get("cnt", 0)

    if not rows:
        text = "Nothing discovered yet\\."
    else:
        parts = [f"🔍 *Latest Discoveries* \\— page {page+1}\n"]
        parts += [fmt_job(r) for r in rows]
        text = "\n\n─────\n".join(parts)

    nav = []
    if page > 0:
        nav.append(InlineKeyboardButton("◀", callback_data=f"discover:{page-1}"))
    if (page+1)*PAGE_SIZE < total:
        nav.append(InlineKeyboardButton("Next ▶", callback_data=f"discover:{page+1}"))
    kb = InlineKeyboardMarkup([nav, [InlineKeyboardButton("🏠 Menu", callback_data="menu")]])
    await _reply(update, text, kb, edit)

# ── Admin callbacks ─────────────────────────────────────────────────────────────
async def _handle_admin_cb(query, action: str):
    if query.from_user.id != ADMIN_CHAT_ID:
        await query.answer("Admin only", show_alert=True); return

    if action == "stats":
        jobs      = db_query("SELECT COUNT(*) cnt FROM jobs", many=False)
        companies = db_query("SELECT COUNT(*) cnt FROM discovered_platforms", many=False)
        schools   = db_query("SELECT COUNT(*) cnt FROM schools", many=False)
        channels  = db_query("SELECT COUNT(*) cnt FROM discovery_channels WHERE active=true", many=False)
        new_24h   = db_query(
            "SELECT COUNT(*) cnt FROM jobs WHERE created_at > NOW() - INTERVAL '24 hours'",
            many=False
        )
        text = (
            f"📊 *System Stats*\n\n"
            f"💼 Total jobs: `{(jobs or {}).get('cnt','?')}`\n"
            f"🆕 Last 24h: `{(new_24h or {}).get('cnt','?')}`\n"
            f"🏢 Companies: `{(companies or {}).get('cnt','?')}`\n"
            f"🎓 Schools: `{(schools or {}).get('cnt','?')}`\n"
            f"📡 Active channels: `{(channels or {}).get('cnt','?')}`"
        )
        await query.edit_message_text(
            text, parse_mode=ParseMode.MARKDOWN_V2,
            reply_markup=InlineKeyboardMarkup([[
                InlineKeyboardButton("🔙 Admin", callback_data="admin:"),
                InlineKeyboardButton("🏠 Menu",  callback_data="menu"),
            ]])
        )

    elif action == "channels":
        rows = db_query(
            "SELECT name, platform, active FROM discovery_channels LIMIT 10",
            many=True
        )
        if rows:
            lines = [f"`{r['name'][:30]}` \\({r['platform']}\\) {'✅' if r['active'] else '❌'}"
                     for r in rows]
            text = "📡 *Active Channels \\(first 10\\)*\n\n" + "\n".join(lines)
        else:
            text = "No channels configured\\."
        await query.edit_message_text(
            text, parse_mode=ParseMode.MARKDOWN_V2,
            reply_markup=InlineKeyboardMarkup([[
                InlineKeyboardButton("🔙 Admin", callback_data="admin:"),
            ]])
        )

    elif action == "scan":
        await query.edit_message_text(
            "🔄 Scan triggered — check VPS logs for progress\\.",
            parse_mode=ParseMode.MARKDOWN_V2
        )

    else:
        await query.answer()

# ── Proactive push jobs ────────────────────────────────────────────────────────
_last_job_id   = 0
_last_school_id = 0

async def push_new_jobs(ctx: ContextTypes.DEFAULT_TYPE):
    """Poll DB for new jobs and push to admin chat (and future subscriber list)."""
    global _last_job_id
    try:
        rows = db_query(
            "SELECT id, title, company, url, sector FROM jobs "
            "WHERE id > %s ORDER BY id ASC LIMIT 10",
            (_last_job_id,), many=True
        )
        if not rows:
            return
        for r in rows:
            _last_job_id = max(_last_job_id, r["id"])
            text = (
                f"🆕 *New Job Alert\\!*\n\n"
                f"💼 *{_esc(r['title'][:60])}*\n"
                f"🏢 {_esc(r['company'][:40])} • `{(r['sector'] or 'gig').upper()}`"
            )
            if r.get("url"):
                text += f"\n[🔗 View Job]({r['url']})"
            kb = InlineKeyboardMarkup([[
                InlineKeyboardButton("💼 More Jobs", callback_data="jobs:0:all"),
                InlineKeyboardButton("🏠 Menu",      callback_data="menu"),
            ]])
            await ctx.bot.send_message(
                ADMIN_CHAT_ID, text,
                parse_mode=ParseMode.MARKDOWN_V2,
                reply_markup=kb,
                disable_web_page_preview=True
            )
    except Exception as e:
        log.error("push_new_jobs error: %s", e)

async def push_new_schools(ctx: ContextTypes.DEFAULT_TYPE):
    """Poll DB for new schools and notify."""
    global _last_school_id
    try:
        rows = db_query(
            "SELECT id, name, url, type FROM schools WHERE id > %s ORDER BY id ASC LIMIT 5",
            (_last_school_id,), many=True
        )
        if not rows:
            return
        for r in rows:
            _last_school_id = max(_last_school_id, r["id"])
            text = (
                f"🎓 *New School Found\\!*\n\n"
                f"*{_esc(r['name'][:60])}*\n"
                f"📋 {_esc(r.get('type') or 'Institution')}"
            )
            if r.get("url"):
                text += f"\n[🌐 Visit]({r['url']})"
            await ctx.bot.send_message(
                ADMIN_CHAT_ID, text,
                parse_mode=ParseMode.MARKDOWN_V2,
                disable_web_page_preview=True
            )
    except Exception as e:
        log.error("push_new_schools: %s", e)

async def daily_digest(ctx: ContextTypes.DEFAULT_TYPE):
    """Morning summary at 8am Nairobi time (UTC+3 → 05:00 UTC)."""
    try:
        jobs_24h  = db_query(
            "SELECT COUNT(*) cnt FROM jobs WHERE created_at > NOW() - INTERVAL '24 hours'",
            many=False
        )
        total_co  = db_query("SELECT COUNT(*) cnt FROM discovered_platforms", many=False)
        n_jobs    = (jobs_24h or {}).get("cnt", 0)
        n_co      = (total_co or {}).get("cnt", 0)
        text = (
            f"☀️ *Morning Digest \\— {datetime.now().strftime('%b %d')}*\n\n"
            f"💼 New jobs last 24h: *{n_jobs}*\n"
            f"🏢 Companies tracked: *{n_co}*\n\n"
            f"Have a productive day\\!"
        )
        await ctx.bot.send_message(
            ADMIN_CHAT_ID, text,
            parse_mode=ParseMode.MARKDOWN_V2,
            reply_markup=main_menu_kb()
        )
    except Exception as e:
        log.error("daily_digest: %s", e)

# ── Smart quick-reply suggestions ─────────────────────────────────────────────
COMMON_QUESTIONS = {
    "annotation":    ("Looking for annotation jobs?", "jobs:0:annotation"),
    "annotate":      ("Looking for annotation jobs?", "jobs:0:annotation"),
    "school":        ("Browse online schools?",        "schools:0:all"),
    "enroll":        ("Browse online schools?",        "schools:0:all"),
    "community":     ("Filter to community colleges?","schools:0:community"),
    "gig":           ("Browse gig work?",             "jobs:0:gig"),
    "remote":        ("Browse all remote jobs?",      "jobs:0:all"),
    "company":       ("Browse company career pages?", "companies:0"),
    "career":        ("Browse company career pages?", "companies:0"),
    "latest":        ("See latest discoveries?",      "discover:0"),
    "new":           ("See what's new?",              "discover:0"),
}

async def on_message(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    text = (update.message.text or "").lower()
    for kw, (label, cb) in COMMON_QUESTIONS.items():
        if kw in text:
            await update.message.reply_text(
                f"💡 *Quick suggestion:* {label}",
                parse_mode=ParseMode.MARKDOWN_V2,
                reply_markup=InlineKeyboardMarkup([[
                    InlineKeyboardButton(label, callback_data=cb),
                    InlineKeyboardButton("🏠 Menu", callback_data="menu"),
                ]])
            )
            return
    # Generic fallback
    await update.message.reply_text(
        "Use the menu to browse jobs, schools, and discoveries:",
        reply_markup=main_menu_kb()
    )

# ── Utility ─────────────────────────────────────────────────────────────────────
async def _reply(update: Update, text: str, kb: InlineKeyboardMarkup,
                 edit: bool = False):
    msg = update.callback_query.message if edit and update.callback_query else None
    try:
        if msg:
            await msg.edit_text(
                text[:4000], parse_mode=ParseMode.MARKDOWN_V2,
                reply_markup=kb, disable_web_page_preview=True
            )
        else:
            m = update.effective_message
            await m.reply_text(
                text[:4000], parse_mode=ParseMode.MARKDOWN_V2,
                reply_markup=kb, disable_web_page_preview=True
            )
    except Exception as e:
        log.warning("Reply failed: %s", e)
        try:
            target = msg or update.effective_message
            await target.reply_text(str(text[:500]), reply_markup=kb)
        except Exception:
            pass

# ── Main ───────────────────────────────────────────────────────────────────────
def main():
    os.makedirs(os.path.join(os.path.dirname(__file__), "..", "logs"), exist_ok=True)

    app = Application.builder().token(BOT_TOKEN).build()

    # Commands
    app.add_handler(CommandHandler("start",     cmd_start))
    app.add_handler(CommandHandler("menu",      cmd_menu))
    app.add_handler(CommandHandler("jobs",      cmd_jobs))
    app.add_handler(CommandHandler("schools",   cmd_schools))
    app.add_handler(CommandHandler("discover",  cmd_discover))
    app.add_handler(CommandHandler("stats",     cmd_stats))
    app.add_handler(CommandHandler("admin",     cmd_admin))
    app.add_handler(CommandHandler("broadcast", cmd_broadcast))

    # Callbacks
    app.add_handler(CallbackQueryHandler(on_callback))

    # Free-text messages → smart suggestions
    app.add_handler(MessageHandler(
        filters.TEXT & ~filters.COMMAND, on_message
    ))

    # Proactive jobs
    jq: JobQueue = app.job_queue
    jq.run_repeating(push_new_jobs,   interval=POLL_INTERVAL, first=30)
    jq.run_repeating(push_new_schools, interval=POLL_INTERVAL * 2, first=60)
    # Daily digest at 05:00 UTC (08:00 Nairobi)
    jq.run_daily(daily_digest, time=datetime.strptime("05:00", "%H:%M").replace(
        tzinfo=timezone.utc
    ).timetz())

    log.info("CareerBridge bot starting...")
    app.run_polling(allowed_updates=Update.ALL_TYPES)

if __name__ == "__main__":
    main()
