"""
telegram_bot.py — CareerBridge Telegram Bot (VPS)
==================================================
Primary user interface. Runs on VPS alongside the discovery services.
Connects directly to local PostgreSQL (localhost:5432) — no SSH tunnel.
"""
from __future__ import annotations

import json
import logging
import os
import sys
import textwrap
from datetime import datetime, timezone
from functools import wraps


# ── Load .env ──────────────────────────────────────────────────────────────────

def _load_env(path: str = "/opt/corvus/.env") -> None:
    try:
        with open(path) as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                key, _, val = line.partition("=")
                key = key.strip()
                val = val.strip().strip('"').strip("'")
                if key and key not in os.environ:
                    os.environ[key] = val
    except FileNotFoundError:
        pass

_load_env()


# ── Logging ────────────────────────────────────────────────────────────────────

LOG_DIR = "/opt/corvus/logs"
os.makedirs(LOG_DIR, exist_ok=True)

logging.basicConfig(
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    level=logging.INFO,
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler(os.path.join(LOG_DIR, "telegram_bot.log")),
    ],
)
log = logging.getLogger("corvus_bot")


# ── Telegram imports ───────────────────────────────────────────────────────────

from telegram import (
    Update, InlineKeyboardButton, InlineKeyboardMarkup,
    WebAppInfo, BotCommand,
)
from telegram.ext import (
    Application, CommandHandler, CallbackQueryHandler,
    MessageHandler, filters, ContextTypes, JobQueue,
)
from telegram.constants import ParseMode


# ── Config ─────────────────────────────────────────────────────────────────────

BOT_TOKEN     = os.environ["TELEGRAM_BOT_TOKEN"]
ADMIN_CHAT_ID = int(os.environ["TELEGRAM_ADMIN_CHAT_ID"])
WEBAPP_URL    = "https://nibrah3.github.io/Corvus/webapp/"
PAGE_SIZE     = 5
POLL_INTERVAL = 300   # 5 min

# Private service — only these Telegram user IDs may interact with the bot.
# Add additional IDs here if you ever share access with a trusted person.
_WHITELIST: frozenset[int] = frozenset({ADMIN_CHAT_ID})

# Bot persona — sets the voice for all user-facing messages.
_BOT_PERSONA = (
    "CareerBridge is your personal remote-work intelligence assistant. "
    "It surfaces verified opportunities — annotation gigs, remote jobs, online schools — "
    "matched to your workflow. Responses are concise, direct, and action-oriented."
)


# ── DB ─────────────────────────────────────────────────────────────────────────

try:
    import psycopg2
    import psycopg2.extras
    _DB_DSN = os.environ.get("VPS_PG_DSN",
                  "postgresql://corvus:corvus-local-password@localhost:5432/careerbridge")
    def get_db():
        return psycopg2.connect(_DB_DSN, connect_timeout=10)
    HAS_DB = True
except Exception:
    HAS_DB = False
    log.warning("psycopg2 unavailable — DB features disabled")


def db_query(sql: str, params: tuple = (), many: bool = False):
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


# ── Permission decorators ──────────────────────────────────────────────────────

def private_only(func):
    """Gate: only whitelisted users may interact with the bot at all."""
    @wraps(func)
    async def wrapper(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
        uid = update.effective_user.id if update.effective_user else None
        if uid not in _WHITELIST:
            log.info("Blocked non-whitelisted user %s", uid)
            if update.effective_message:
                await update.effective_message.reply_text(
                    "This is a private assistant. Access is restricted."
                )
            return
        return await func(update, ctx)
    return wrapper


def admin_only(func):
    """Gate: only the admin (ADMIN_CHAT_ID) may call admin commands."""
    @wraps(func)
    async def wrapper(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
        uid = update.effective_user.id if update.effective_user else None
        if uid != ADMIN_CHAT_ID:
            await update.effective_message.reply_text("Admin access required.")
            return
        return await func(update, ctx)
    return wrapper


# ── Keyboards ──────────────────────────────────────────────────────────────────

def main_menu_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton("💼 Browse Jobs",  callback_data="jobs:0:all"),
            InlineKeyboardButton("🎓 Schools",      callback_data="schools:0:best"),
        ],
        [
            InlineKeyboardButton("🏢 Companies",    callback_data="companies:0"),
            InlineKeyboardButton("🔍 Latest Finds", callback_data="discover:0"),
        ],
        [
            InlineKeyboardButton("🔎 Search Now",   callback_data="srch:"),
        ],
        [
            InlineKeyboardButton("📊 Open Full App", web_app=WebAppInfo(url=WEBAPP_URL)),
        ],
    ])


def school_filter_kb(active: str = "best") -> InlineKeyboardMarkup:
    filters_list = [
        ("🏆 Best Match",     "best"),
        ("All",              "all"),
        ("Community",        "community"),
        ("No ID",            "noid"),
        ("Monthly Enroll",   "monthly"),
        ("Instant Accept",   "instant"),
        ("No Transcript",    "notranscript"),
        ("Refund Policy",    "refund"),
    ]
    rows = []
    row = []
    for label, key in filters_list:
        row.append(InlineKeyboardButton(
            ("✅ " if key == active else "") + label,
            callback_data=f"schools:0:{key}"
        ))
        if len(row) == 2:
            rows.append(row)
            row = []
    if row:
        rows.append(row)
    rows.append([InlineKeyboardButton("🏠 Menu", callback_data="menu")])
    return InlineKeyboardMarkup(rows)


def search_menu_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton("💼 Jobs",      callback_data="srch_t:jobs"),
            InlineKeyboardButton("🎓 Schools",   callback_data="srch_t:schools"),
            InlineKeyboardButton("🏢 Companies", callback_data="srch_t:companies"),
        ],
        [InlineKeyboardButton("🏠 Cancel", callback_data="menu")],
    ])


def _job_search_filter_kb(sel: str = "") -> InlineKeyboardMarkup:
    opts = [("All Jobs", "all"), ("💰 Gig", "gig"),
            ("✏️ Annotation", "annotation"), ("📚 Education", "education")]
    rows = [
        [InlineKeyboardButton(("✅ " if k == sel else "") + lbl,
                              callback_data=f"srch_f:jobs:{k}") for lbl, k in opts[:2]],
        [InlineKeyboardButton(("✅ " if k == sel else "") + lbl,
                              callback_data=f"srch_f:jobs:{k}") for lbl, k in opts[2:]],
        [InlineKeyboardButton("🔍 Keyword search", callback_data=f"srch_kw:jobs:{sel or 'all'}"),
         InlineKeyboardButton("🏠 Menu",           callback_data="menu")],
    ]
    return InlineKeyboardMarkup(rows)


def _school_search_filter_kb(sel: str = "") -> InlineKeyboardMarkup:
    opts = [
        ("🏆 Best", "best"), ("All", "all"), ("🏫 Community", "community"),
        ("✅ No ID", "noid"), ("📅 Monthly", "monthly"), ("⚡ Instant", "instant"),
        ("📄 No Transcript", "notranscript"), ("💰 Refund", "refund"),
    ]
    rows, pair = [], []
    for lbl, k in opts:
        pair.append(InlineKeyboardButton(("✅ " if k == sel else "") + lbl,
                                         callback_data=f"srch_f:schools:{k}"))
        if len(pair) == 2:
            rows.append(pair); pair = []
    if pair:
        rows.append(pair)
    rows.append([InlineKeyboardButton("🔍 Keyword search", callback_data=f"srch_kw:schools:{sel or 'best'}"),
                 InlineKeyboardButton("🏠 Menu",           callback_data="menu")])
    return InlineKeyboardMarkup(rows)


def pager_row(prefix: str, page: int, total: int, extra: str = "") -> list:
    btns = []
    if page > 0:
        btns.append(InlineKeyboardButton("◀", callback_data=f"{prefix}:{page-1}:{extra}"))
    if (page + 1) * PAGE_SIZE < total:
        btns.append(InlineKeyboardButton("Next ▶", callback_data=f"{prefix}:{page+1}:{extra}"))
    return btns


# ── Formatters ─────────────────────────────────────────────────────────────────

def _esc(text: str) -> str:
    if not text:
        return ""
    for ch in r"\_*[]()~`>#+-=|{}.!":
        text = text.replace(ch, f"\\{ch}")
    return text


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
    parts = [
        f"💼 *{_esc(title)}*",
        f"🏢 {_esc(company)}  •  `{sector}`{posted}",
    ]
    if desc:
        parts.append(f"_{_esc(desc)}_")
    if url:
        parts.append(f"[🔗 View Job]({url})")
    return "\n".join(parts)


def fmt_school(s: dict) -> str:
    score   = s.get("criteria_score", 0)
    star    = "🏆 " if score == 6 else ("⭐ " if score >= 4 else "🎓 ")
    name    = f"{star}{s.get('name', 'Unknown')[:75]}"
    url     = s.get("enrollment_url") or s.get("url", "")
    desc    = textwrap.shorten(s.get("evidence") or "", width=120, placeholder="…")
    flags   = s.get("_flags", [])
    badge   = " • ".join(flags[:4]) if flags else f"{score}/6 criteria"
    parts   = [f"🎓 *{_esc(name)}*", f"📋 {_esc(badge)}"]
    if desc:
        parts.append(f"_{_esc(desc)}_")
    if url:
        parts.append(f"[🌐 Enrollment Page]({url})")
    return "\n".join(parts)


def fmt_company(c: dict) -> str:
    name = c.get("company", "Unknown")[:60]
    url  = c.get("careers_url", "")
    src  = c.get("source", "")
    parts = [f"🏢 *{_esc(name)}*"]
    if url:
        parts.append(f"[🔗 Careers Page]({url})")
    if src:
        parts.append(f"📡 Source: `{_esc(src)}`")
    return "\n".join(parts)


# ── Handlers ───────────────────────────────────────────────────────────────────

@private_only
async def cmd_start(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    name = update.effective_user.first_name or "there"
    text = (
        f"👋 Hey *{_esc(name)}*\\!\n\n"
        "Welcome back to *CareerBridge* — your personal remote work intelligence hub\\.\n\n"
        "I continuously scan for:\n"
        "💼 *Annotation & gig jobs* — Scale AI, Remotasks, and more\n"
        "🎓 *Flexible online schools* — monthly enrollment, no ID, instant acceptance\n"
        "🏢 *Company career pages* — direct remote hiring pipelines\n\n"
        "Everything is indexed and ranked for you\\. Tap below to explore\\."
    )
    await update.message.reply_text(
        text, parse_mode=ParseMode.MARKDOWN_V2, reply_markup=main_menu_kb()
    )


@private_only
async def cmd_menu(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    await update.message.reply_text(
        "📱 *CareerBridge*", parse_mode=ParseMode.MARKDOWN_V2,
        reply_markup=main_menu_kb()
    )


@private_only
async def cmd_jobs(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    await _send_jobs(update, ctx, page=0, sector="all")


@private_only
async def cmd_schools(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    await _send_schools(update, ctx, page=0, filt="best")


@private_only
async def cmd_discover(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    await _send_discover(update, ctx, page=0)


@private_only
async def cmd_stats(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    jobs      = db_query("SELECT COUNT(*) cnt FROM jobs", many=False)
    companies = db_query("SELECT COUNT(*) cnt FROM discovered_platforms", many=False)
    schools   = db_query("SELECT COUNT(*) cnt FROM schools", many=False)
    channels  = db_query("SELECT COUNT(*) cnt FROM discovery_channels WHERE active=true", many=False)
    j  = (jobs or {}).get("cnt", "?")
    c  = (companies or {}).get("cnt", "?")
    s  = (schools or {}).get("cnt", "?")
    ch = (channels or {}).get("cnt", "?")
    await update.effective_message.reply_text(
        f"📊 *System Stats*\n\n"
        f"💼 Jobs indexed: `{j}`\n"
        f"🏢 Companies tracked: `{c}`\n"
        f"🎓 Schools listed: `{s}`\n"
        f"📡 Active channels: `{ch}`",
        parse_mode=ParseMode.MARKDOWN_V2,
        reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🏠 Menu", callback_data="menu")]])
    )


@private_only
async def cmd_search(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    await update.message.reply_text(
        "🔍 *Search CareerBridge*\n\nWhat are you looking for?",
        parse_mode=ParseMode.MARKDOWN_V2,
        reply_markup=search_menu_kb()
    )


@admin_only
async def cmd_admin(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    await update.message.reply_text(
        "🛠 *Admin Panel*",
        parse_mode=ParseMode.MARKDOWN_V2,
        reply_markup=InlineKeyboardMarkup([
            [
                InlineKeyboardButton("📊 Full Stats",  callback_data="admin:stats"),
                InlineKeyboardButton("📡 Channels",    callback_data="admin:channels"),
            ],
            [
                InlineKeyboardButton("🔄 Force Scan",  callback_data="admin:scan"),
                InlineKeyboardButton("🏠 Menu",        callback_data="menu"),
            ],
        ])
    )


@admin_only
async def cmd_broadcast(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    msg = " ".join(ctx.args) if ctx.args else ""
    if not msg:
        await update.message.reply_text("Usage: /broadcast <message>")
        return
    await update.message.reply_text(f"📣 Broadcast sent: {msg[:100]}")


# ── Callback router ────────────────────────────────────────────────────────────

@private_only
async def on_callback(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
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
        filt = parts[2] if len(parts) > 2 else "best"
        await _send_schools(update, ctx, page, filt, edit=True)
    elif parts[0] == "companies":
        page = int(parts[1]) if len(parts) > 1 else 0
        await _send_companies(update, ctx, page, edit=True)
    elif parts[0] == "discover":
        page = int(parts[1]) if len(parts) > 1 else 0
        await _send_discover(update, ctx, page, edit=True)
    elif parts[0] == "admin":
        await _handle_admin_cb(query, parts[1] if len(parts) > 1 else "")
    elif data == "srch:" or data == "srch":
        await query.edit_message_text(
            "🔍 *Search CareerBridge*\n\nWhat are you looking for?",
            parse_mode=ParseMode.MARKDOWN_V2,
            reply_markup=search_menu_kb()
        )
    elif parts[0] == "srch_t":
        stype = parts[1] if len(parts) > 1 else "jobs"
        if stype == "jobs":
            await query.edit_message_text(
                "💼 *Search Jobs*\n\nChoose a filter or type a keyword:",
                parse_mode=ParseMode.MARKDOWN_V2,
                reply_markup=_job_search_filter_kb()
            )
        elif stype == "schools":
            await query.edit_message_text(
                "🎓 *Search Schools*\n\nChoose a filter or type a keyword:",
                parse_mode=ParseMode.MARKDOWN_V2,
                reply_markup=_school_search_filter_kb()
            )
        elif stype == "companies":
            await _search_companies(update, ctx, edit=True)
    elif parts[0] == "srch_f":
        stype = parts[1] if len(parts) > 1 else "jobs"
        sfilt = parts[2] if len(parts) > 2 else "all"
        if stype == "jobs":
            await _search_jobs(update, ctx, filt=sfilt, edit=True)
        elif stype == "schools":
            await _search_schools(update, ctx, filt=sfilt, edit=True)
    elif parts[0] == "srch_kw":
        stype = parts[1] if len(parts) > 1 else "jobs"
        sfilt = parts[2] if len(parts) > 2 else "all"
        ctx.user_data["search_pending"] = {"type": stype, "filter": sfilt}
        await query.edit_message_text(
            f"🔍 *Keyword Search*\n\nType your search term for *{_esc(stype)}*:",
            parse_mode=ParseMode.MARKDOWN_V2,
            reply_markup=InlineKeyboardMarkup([[
                InlineKeyboardButton("🚫 Cancel", callback_data="menu")
            ]])
        )


# ── Page senders ───────────────────────────────────────────────────────────────

_SCORE_EXPR = (
    "(no_id_verification::int + monthly_enrollment::int + instant_acceptance::int + "
    "no_transcript_required::int + monthly_refund::int + community_college::int)"
)

_SCHOOL_FILTER_SQL = {
    "community":    "type ILIKE '%community%'",
    "noid":         "no_id_verification = true",
    "monthly":      "monthly_enrollment = true",
    "instant":      "instant_acceptance = true",
    "notranscript": "no_transcript_required = true",
    "refund":       "monthly_refund = true",
    "best":         f"{_SCORE_EXPR} >= 4",
}


async def _send_jobs(update: Update, ctx, page: int, sector: str,
                     edit: bool = False) -> None:
    where  = "" if sector == "all" else "WHERE sector = %s"
    params = (sector,) if sector != "all" else ()
    total  = ((db_query(f"SELECT COUNT(*) cnt FROM jobs {where}", params, many=False) or {}).get("cnt") or 0)
    rows   = db_query(
        f"SELECT title, company, url, sector, description, posted_at FROM jobs "
        f"{where} ORDER BY id DESC LIMIT %s OFFSET %s",
        params + (PAGE_SIZE, page * PAGE_SIZE), many=True
    )

    if not rows:
        text = "No jobs found for this filter\\."
    else:
        header = f"💼 *Jobs* \\— page {page+1} of {max(1,(total+PAGE_SIZE-1)//PAGE_SIZE)} \\({total} total\\)\n"
        parts  = [header] + [fmt_job(r) for r in rows]
        text   = "\n\n─────\n".join(parts)

    nav = pager_row("jobs", page, total, sector)
    kb = InlineKeyboardMarkup([
        nav,
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
                        edit: bool = False) -> None:
    where = f"WHERE {_SCHOOL_FILTER_SQL[filt]}" if filt in _SCHOOL_FILTER_SQL else ""
    total = ((db_query(f"SELECT COUNT(*) cnt FROM schools {where}", many=False) or {}).get("cnt") or 0)
    rows  = db_query(
        f"SELECT name, url, enrollment_url, type, evidence, "
        f"no_id_verification, monthly_enrollment, instant_acceptance, "
        f"no_transcript_required, monthly_refund, community_college, "
        f"{_SCORE_EXPR} AS criteria_score "
        f"FROM schools {where} "
        f"ORDER BY {_SCORE_EXPR} DESC, name LIMIT %s OFFSET %s",
        (PAGE_SIZE, page * PAGE_SIZE), many=True
    )

    if not rows:
        text = "No schools match this filter\\. Still scraping\\!"
    else:
        header = (
            f"🏆 *Best Match Schools* \\— {total} meeting 4\\+ criteria"
            if filt == "best"
            else f"🎓 *Schools* \\— page {page+1}  \\({total} total\\)"
        )
        parts = [header + "\n"]
        for r in rows:
            score = r.get("criteria_score", 0)
            flags = []
            if r.get("community_college"):      flags.append("🏫 Community")
            if r.get("no_id_verification"):     flags.append("✅ No ID")
            if r.get("monthly_enrollment"):     flags.append("📅 Monthly")
            if r.get("instant_acceptance"):     flags.append("⚡ Instant")
            if r.get("no_transcript_required"): flags.append("📄 No Transcript")
            if r.get("monthly_refund"):         flags.append("💰 Refund")
            rd = dict(r)
            rd["_flags"] = flags
            parts.append(fmt_school(rd))
        text = "\n\n─────\n".join(parts)

    nav = pager_row("schools", page, total, filt)
    kb = InlineKeyboardMarkup([
        nav,
        [
            InlineKeyboardButton("🏆 Best Match", callback_data="schools:0:best"),
            InlineKeyboardButton("All",           callback_data="schools:0:all"),
        ],
        [
            InlineKeyboardButton("Community",     callback_data="schools:0:community"),
            InlineKeyboardButton("No ID",         callback_data="schools:0:noid"),
            InlineKeyboardButton("Monthly",       callback_data="schools:0:monthly"),
        ],
        [
            InlineKeyboardButton("Instant",       callback_data="schools:0:instant"),
            InlineKeyboardButton("No Transcript", callback_data="schools:0:notranscript"),
            InlineKeyboardButton("🏠 Menu",       callback_data="menu"),
        ],
    ])
    await _reply(update, text, kb, edit)


async def _send_companies(update: Update, ctx, page: int, edit: bool = False) -> None:
    total = ((db_query("SELECT COUNT(*) cnt FROM discovered_platforms", many=False) or {}).get("cnt") or 0)
    rows  = db_query(
        "SELECT company, careers_url, source, last_checked FROM discovered_platforms "
        "ORDER BY id DESC LIMIT %s OFFSET %s",
        (PAGE_SIZE, page * PAGE_SIZE), many=True
    )
    if not rows:
        text = "No companies tracked yet\\."
    else:
        parts = [f"🏢 *Companies* \\— page {page+1}  \\({total} tracked\\)\n"]
        parts += [fmt_company(r) for r in rows]
        text   = "\n\n─────\n".join(parts)

    nav = pager_row("companies", page, total, "")
    kb  = InlineKeyboardMarkup([nav, [InlineKeyboardButton("🏠 Menu", callback_data="menu")]])
    await _reply(update, text, kb, edit)


async def _send_discover(update: Update, ctx, page: int, edit: bool = False) -> None:
    total = ((db_query("SELECT COUNT(*) cnt FROM jobs", many=False) or {}).get("cnt") or 0)
    rows  = db_query(
        "SELECT title, company, url, sector, created_at FROM jobs "
        "ORDER BY id DESC LIMIT %s OFFSET %s",
        (PAGE_SIZE, page * PAGE_SIZE), many=True
    )
    if not rows:
        text = "Nothing discovered yet\\."
    else:
        parts = [f"🔍 *Latest Discoveries* \\— page {page+1}\n"]
        parts += [fmt_job(r) for r in rows]
        text   = "\n\n─────\n".join(parts)

    nav = pager_row("discover", page, total, "")
    kb  = InlineKeyboardMarkup([nav, [InlineKeyboardButton("🏠 Menu", callback_data="menu")]])
    await _reply(update, text, kb, edit)


# ── On-demand search senders ───────────────────────────────────────────────────

async def _search_jobs(update: Update, ctx, filt: str = "all",
                       keyword: str = "", edit: bool = False) -> None:
    conds: list[str] = []
    vals: list = []
    if filt != "all":
        conds.append("sector = %s")
        vals.append(filt)
    if keyword:
        kw = f"%{keyword}%"
        conds.append("(title ILIKE %s OR company ILIKE %s OR description ILIKE %s)")
        vals += [kw, kw, kw]
    where = ("WHERE " + " AND ".join(conds)) if conds else ""
    total = ((db_query(f"SELECT COUNT(*) cnt FROM jobs {where}",
                       tuple(vals), many=False) or {}).get("cnt") or 0)
    rows  = db_query(
        f"SELECT title, company, url, sector, description, posted_at FROM jobs "
        f"{where} ORDER BY id DESC LIMIT %s OFFSET %s",
        tuple(vals) + (PAGE_SIZE, 0), many=True
    )
    kw_note = f' — _{_esc(keyword)}_' if keyword else ""
    header  = f"💼 *Job Search*{kw_note} \\({total} found\\)\n"
    text    = header + ("\n\n─────\n".join(fmt_job(r) for r in rows) if rows else "No jobs matched\\.")
    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("🔄 Change filter",  callback_data="srch_t:jobs"),
         InlineKeyboardButton("🔍 Keyword",        callback_data=f"srch_kw:jobs:{filt}"),
         InlineKeyboardButton("🏠 Menu",           callback_data="menu")],
    ])
    await _reply(update, text, kb, edit)


async def _search_schools(update: Update, ctx, filt: str = "best",
                          keyword: str = "", edit: bool = False) -> None:
    conds: list[str] = []
    vals: list = []
    if filt in _SCHOOL_FILTER_SQL:
        conds.append(_SCHOOL_FILTER_SQL[filt])
    if keyword:
        kw = f"%{keyword}%"
        conds.append("(name ILIKE %s OR evidence ILIKE %s)")
        vals += [kw, kw]
    where = ("WHERE " + " AND ".join(conds)) if conds else ""
    total = ((db_query(f"SELECT COUNT(*) cnt FROM schools {where}",
                       tuple(vals), many=False) or {}).get("cnt") or 0)
    rows  = db_query(
        f"SELECT name, url, enrollment_url, type, evidence, "
        f"no_id_verification, monthly_enrollment, instant_acceptance, "
        f"no_transcript_required, monthly_refund, community_college, "
        f"{_SCORE_EXPR} AS criteria_score "
        f"FROM schools {where} ORDER BY {_SCORE_EXPR} DESC LIMIT %s OFFSET %s",
        tuple(vals) + (PAGE_SIZE, 0), many=True
    )
    kw_note = f' — _{_esc(keyword)}_' if keyword else ""
    header  = f"🎓 *School Search*{kw_note} \\({total} found\\)\n"
    parts   = [header]
    for r in (rows or []):
        flags = []
        if r.get("community_college"):      flags.append("🏫 Community")
        if r.get("no_id_verification"):     flags.append("✅ No ID")
        if r.get("monthly_enrollment"):     flags.append("📅 Monthly")
        if r.get("instant_acceptance"):     flags.append("⚡ Instant")
        if r.get("no_transcript_required"): flags.append("📄 No Transcript")
        if r.get("monthly_refund"):         flags.append("💰 Refund")
        rd = dict(r); rd["_flags"] = flags
        parts.append(fmt_school(rd))
    text = ("\n\n─────\n".join(parts)) if rows else (header + "No schools matched\\.")
    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("🔄 Change filter",  callback_data="srch_t:schools"),
         InlineKeyboardButton("🔍 Keyword",        callback_data=f"srch_kw:schools:{filt}"),
         InlineKeyboardButton("🏠 Menu",           callback_data="menu")],
    ])
    await _reply(update, text, kb, edit)


async def _search_companies(update: Update, ctx, keyword: str = "",
                            edit: bool = False) -> None:
    conds: list[str] = []
    vals: list = []
    if keyword:
        kw = f"%{keyword}%"
        conds.append("(company ILIKE %s OR careers_url ILIKE %s)")
        vals += [kw, kw]
    where = ("WHERE " + " AND ".join(conds)) if conds else ""
    total = ((db_query(f"SELECT COUNT(*) cnt FROM discovered_platforms {where}",
                       tuple(vals), many=False) or {}).get("cnt") or 0)
    rows  = db_query(
        f"SELECT company, careers_url, source, last_checked FROM discovered_platforms "
        f"{where} ORDER BY id DESC LIMIT %s OFFSET %s",
        tuple(vals) + (PAGE_SIZE, 0), many=True
    )
    kw_note = f' — _{_esc(keyword)}_' if keyword else ""
    header  = f"🏢 *Company Search*{kw_note} \\({total} found\\)\n"
    text    = header + ("\n\n─────\n".join(fmt_company(r) for r in rows) if rows else "No companies matched\\.")
    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("🔍 Keyword search", callback_data="srch_kw:companies:"),
         InlineKeyboardButton("🏠 Menu",           callback_data="menu")],
    ])
    await _reply(update, text, kb, edit)


# ── Admin callbacks ────────────────────────────────────────────────────────────

async def _handle_admin_cb(query, action: str) -> None:
    if query.from_user.id != ADMIN_CHAT_ID:
        await query.answer("Admin only", show_alert=True)
        return

    if action == "stats":
        jobs    = db_query("SELECT COUNT(*) cnt FROM jobs", many=False)
        cos     = db_query("SELECT COUNT(*) cnt FROM discovered_platforms", many=False)
        schools = db_query("SELECT COUNT(*) cnt FROM schools", many=False)
        new24h  = db_query(
            "SELECT COUNT(*) cnt FROM jobs WHERE created_at > NOW() - INTERVAL '24 hours'",
            many=False
        )
        text = (
            f"📊 *System Stats*\n\n"
            f"💼 Total jobs: `{(jobs or {}).get('cnt','?')}`\n"
            f"🆕 Last 24h: `{(new24h or {}).get('cnt','?')}`\n"
            f"🏢 Companies: `{(cos or {}).get('cnt','?')}`\n"
            f"🎓 Schools: `{(schools or {}).get('cnt','?')}`"
        )
        await query.edit_message_text(
            text, parse_mode=ParseMode.MARKDOWN_V2,
            reply_markup=InlineKeyboardMarkup([[
                InlineKeyboardButton("🔙 Admin", callback_data="admin:"),
                InlineKeyboardButton("🏠 Menu",  callback_data="menu"),
            ]])
        )

    elif action == "channels":
        rows = db_query("SELECT name, platform, active FROM discovery_channels LIMIT 10", many=True)
        if rows:
            lines = [
                f"`{r['name'][:30]}` \\({r['platform']}\\) {'✅' if r['active'] else '❌'}"
                for r in rows
            ]
            text = "📡 *Active Channels*\n\n" + "\n".join(lines)
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
            "🔄 Scan triggered — check logs for progress\\.",
            parse_mode=ParseMode.MARKDOWN_V2
        )

    else:
        await query.answer()


# ── Proactive push ─────────────────────────────────────────────────────────────

_last_job_id    = 0
_last_school_id = 0


async def push_new_jobs(ctx: ContextTypes.DEFAULT_TYPE) -> None:
    global _last_job_id
    try:
        rows = db_query(
            "SELECT id, title, company, url, sector FROM jobs "
            "WHERE id > %s ORDER BY id ASC LIMIT 10",
            (_last_job_id,), many=True
        )
        for r in (rows or []):
            _last_job_id = max(_last_job_id, r["id"])
            text = (
                f"🆕 *New Job Alert\\!*\n\n"
                f"💼 *{_esc(r['title'][:60])}*\n"
                f"🏢 {_esc(r['company'][:40])} • `{(r['sector'] or 'gig').upper()}`"
            )
            if r.get("url"):
                text += f"\n[🔗 View Job]({r['url']})"
            await ctx.bot.send_message(
                ADMIN_CHAT_ID, text,
                parse_mode=ParseMode.MARKDOWN_V2,
                reply_markup=InlineKeyboardMarkup([[
                    InlineKeyboardButton("💼 More Jobs", callback_data="jobs:0:all"),
                    InlineKeyboardButton("🏠 Menu",      callback_data="menu"),
                ]]),
                disable_web_page_preview=True,
            )
    except Exception as e:
        log.error("push_new_jobs: %s", e)


async def push_new_schools(ctx: ContextTypes.DEFAULT_TYPE) -> None:
    global _last_school_id
    try:
        rows = db_query(
            "SELECT id, name, url, type FROM schools WHERE id > %s ORDER BY id ASC LIMIT 5",
            (_last_school_id,), many=True
        )
        for r in (rows or []):
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
                disable_web_page_preview=True,
            )
    except Exception as e:
        log.error("push_new_schools: %s", e)


async def daily_digest(ctx: ContextTypes.DEFAULT_TYPE) -> None:
    try:
        jobs_24h = db_query(
            "SELECT COUNT(*) cnt FROM jobs WHERE created_at > NOW() - INTERVAL '24 hours'",
            many=False
        )
        total_co = db_query("SELECT COUNT(*) cnt FROM discovered_platforms", many=False)
        n_jobs   = (jobs_24h or {}).get("cnt", 0)
        n_co     = (total_co or {}).get("cnt", 0)
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


# ── Free-text quick-reply ──────────────────────────────────────────────────────

_QUICK_REPLIES = {
    "annotation": ("Looking for annotation jobs?",      "jobs:0:annotation"),
    "annotate":   ("Looking for annotation jobs?",      "jobs:0:annotation"),
    "school":     ("Browse online schools?",            "schools:0:best"),
    "enroll":     ("Browse online schools?",            "schools:0:best"),
    "community":  ("Filter to community colleges?",     "schools:0:community"),
    "gig":        ("Browse gig work?",                  "jobs:0:gig"),
    "remote":     ("Browse all remote jobs?",           "jobs:0:all"),
    "company":    ("Browse company career pages?",      "companies:0"),
    "career":     ("Browse company career pages?",      "companies:0"),
    "latest":     ("See latest discoveries?",           "discover:0"),
    "new":        ("See what's new?",                   "discover:0"),
    "search":     ("Search CareerBridge?",              "srch:"),
    "find":       ("Search CareerBridge?",              "srch:"),
    "look":       ("Search CareerBridge?",              "srch:"),
}


@private_only
async def on_message(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    text = (update.message.text or "").lower()

    # Pending keyword search from srch_kw callback
    pending = ctx.user_data.get("search_pending")
    if pending:
        ctx.user_data.pop("search_pending", None)
        stype = pending["type"]
        sfilt = pending.get("filter", "all")
        keyword = update.message.text or ""
        if stype == "jobs":
            await _search_jobs(update, ctx, filt=sfilt, keyword=keyword)
        elif stype == "schools":
            await _search_schools(update, ctx, filt=sfilt, keyword=keyword)
        elif stype == "companies":
            await _search_companies(update, ctx, keyword=keyword)
        return

    for kw, (label, cb) in _QUICK_REPLIES.items():
        if kw in text:
            await update.message.reply_text(
                f"💡 *Quick suggestion:* {_esc(label)}",
                parse_mode=ParseMode.MARKDOWN_V2,
                reply_markup=InlineKeyboardMarkup([[
                    InlineKeyboardButton(label, callback_data=cb),
                    InlineKeyboardButton("🏠 Menu", callback_data="menu"),
                ]])
            )
            return
    await update.message.reply_text(
        "Here's what I can help you with right now:",
        reply_markup=main_menu_kb()
    )


# ── Utility ────────────────────────────────────────────────────────────────────

async def _reply(update: Update, text: str, kb: InlineKeyboardMarkup,
                 edit: bool = False) -> None:
    msg = update.callback_query.message if edit and update.callback_query else None
    try:
        if msg:
            await msg.edit_text(
                text[:4000], parse_mode=ParseMode.MARKDOWN_V2,
                reply_markup=kb, disable_web_page_preview=True
            )
        else:
            await update.effective_message.reply_text(
                text[:4000], parse_mode=ParseMode.MARKDOWN_V2,
                reply_markup=kb, disable_web_page_preview=True
            )
    except Exception as e:
        log.warning("Reply failed: %s", e)
        try:
            target = msg or update.effective_message
            await target.reply_text(text[:500], reply_markup=kb)
        except Exception:
            pass


# ── Main ───────────────────────────────────────────────────────────────────────

def main() -> None:
    app = Application.builder().token(BOT_TOKEN).build()

    app.add_handler(CommandHandler("start",     cmd_start))
    app.add_handler(CommandHandler("menu",      cmd_menu))
    app.add_handler(CommandHandler("jobs",      cmd_jobs))
    app.add_handler(CommandHandler("schools",   cmd_schools))
    app.add_handler(CommandHandler("discover",  cmd_discover))
    app.add_handler(CommandHandler("stats",     cmd_stats))
    app.add_handler(CommandHandler("search",    cmd_search))
    app.add_handler(CommandHandler("admin",     cmd_admin))
    app.add_handler(CommandHandler("broadcast", cmd_broadcast))
    app.add_handler(CallbackQueryHandler(on_callback))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, on_message))

    jq: JobQueue = app.job_queue
    jq.run_repeating(push_new_jobs,    interval=POLL_INTERVAL,     first=30)
    jq.run_repeating(push_new_schools, interval=POLL_INTERVAL * 2, first=60)
    jq.run_daily(
        daily_digest,
        time=datetime.strptime("05:00", "%H:%M").replace(tzinfo=timezone.utc).timetz()
    )

    log.info("CareerBridge bot starting on VPS...")
    app.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()
