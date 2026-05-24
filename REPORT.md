# Corvus_Careebridge — Comprehensive Engineering Report

**Generated:** 2026-05-24  
**Project root:** `D:\cb-core`  
**GitHub:** github.com/nibrah3/Corvus_Careebridge  
**GitHub Pages:** https://nibrah3.github.io/Corvus_Careebridge/  

---

## 1. ixBrowser Annotation Pipeline

### What was built
`D:\cb-core\scripts\ixbrowser_annotation_pipeline.py`

An end-to-end computer-vision annotation pipeline using:
- **ixBrowser local REST API** (port 53200) to open an existing anti-detect browser profile
- **Playwright CDP** to connect to the open browser without launching a new one
- **Gemini 2.5-flash** to detect objects and return normalized bounding boxes
- **makesense.ai** (public annotation tool) as the UI for drawing and exporting labels

### Final working sequence

```
1. POST http://127.0.0.1:53200/api/v2/profile-open {"profile_id": 12}
   → Returns CDP debugging_address

2. Playwright: connect_over_cdp(cdp_url)
   → Attach to existing Chromium session

3. Navigate to https://www.makesense.ai
   → Click "Get Started"

4. Upload image via input[type='file'].set_input_files(local_path)
   → Click "Object Detection"

5. Click "Load labels from file"
   → Find any input[type='file'] on page → set_input_files(labels.txt)
   → Click "Start project"

6. Click "Labels" tab (collapses right panel, expands canvas from 340px → 641px)
   → This is critical: without it, mouse drags pan the view instead of drawing

7. Mouse drag on canvas to draw each bounding box
   → If label popup appears, click the label name to assign it

8. Actions → Export Annotations → YOLO/JSON format
```

### Key engineering decisions
- **No exotic JS injection** — pure CDP + Playwright mouse events throughout
- **Canvas expansion trick** — clicking "Labels" tab collapses the side panel, making the canvas wide enough for draw mode to engage correctly (341px → 641px)
- **Gemini JSON parsing** — strips markdown fences, falls back to regex object scan, uses synthetic demo annotations if Gemini unavailable
- **Profile stays open** — `browser.close()` closes the Playwright connection, not the ixBrowser profile

### API endpoint discovery
ixBrowser API prefix is `/api/v2/` (not `/api/v1/browser/`). Discovered by grepping the installed `app.asar` binary.

---

## 2. Telegram Bot — Primary UI

### File
`D:\cb-core\scripts\telegram_bot.py`

### Architecture

```
Application (python-telegram-bot 22.7, async)
├── Public commands
│   ├── /start    → Welcome + main menu keyboard
│   ├── /menu     → Main menu
│   ├── /jobs     → Job browser with sector filters
│   ├── /schools  → School browser (defaults to Best Match filter)
│   ├── /discover → Latest discoveries feed
│   └── /stats    → DB counts
├── Admin-only commands (gated by ADMIN_CHAT_ID check)
│   ├── /admin    → Admin panel with action buttons
│   └── /broadcast <msg> → Broadcast message
├── Callback router
│   └── on_callback → routes jobs:, schools:, companies:, discover:, admin:, menu
├── Free-text handler
│   └── on_message → keyword match → inline suggestion (proactive UX)
└── JobQueue (background)
    ├── push_new_jobs     every 5 min → polls DB for new job IDs
    ├── push_new_schools  every 10 min → polls DB for new school IDs
    └── daily_digest      daily 05:00 UTC (08:00 Nairobi)
```

### Access control
```python
@admin_only   # decorator checks update.effective_user.id == ADMIN_CHAT_ID
async def cmd_admin(update, ctx): ...
```
Non-admins get "⛔ Admin access required" — no information leakage.

### Proactive features
- **New job push** — polls every 5 min, sends alert card with sector badge and job link
- **New school push** — polls every 10 min, sends school card with type info
- **Daily digest** — morning summary (jobs last 24h, companies tracked)
- **Smart keyword suggestions** — user types "annotation" → bot suggests "Looking for annotation jobs?" with inline button. Keywords: annotation, school, enroll, community, gig, remote, company, career, latest, new

### School display priority
Schools default to **Best Match** filter — sorted by how many of the 6 criteria each school meets. Schools meeting 4+ criteria get ⭐, those meeting all 6 get 🏆.

### Config
```
BOT_TOKEN     = TELEGRAM_BOT_TOKEN env var
ADMIN_CHAT_ID = 7994812711
WEBAPP_URL    = https://nibrah3.github.io/Corvus/
PAGE_SIZE     = 5 items/page
POLL_INTERVAL = 300s (5 min)
```

### Run
```bash
py -3 D:\cb-core\scripts\telegram_bot.py
```
Logs to `D:\cb-core\logs\telegram_bot.log`

---

## 3. GitHub Pages Web App

### File
`D:\cb-core\webapp\index.html`

### Stack
- Pure HTML/CSS/JS — no build step, no framework
- **Telegram WebApp SDK** (`telegram-web-app.js`) for native Telegram integration
- Reads static JSON from `https://nibrah3.github.io/Corvus/data/`
- Dark theme with Telegram-style design language

### Views
| View | Data source | Features |
|------|-------------|----------|
| Jobs | `data/jobs.json` | Search bar, sector filter chips, pagination |
| Schools | `data/schools.json` | **Best Match default**, 8 filter chips, criteria score badge on each card |
| Companies | `data/companies.json` | Career page links, ATS source badge |
| Discover | `data/jobs.json` | Latest 30 entries, no filter |

### School card
Each school card shows:
- Trophy icon (🏆 = 6/6, ⭐ = 4-5/6, 🎓 = 1-3/6)
- Criteria score badge (e.g., "5/6 criteria" in green)
- Individual filter badges: Community, No ID, Monthly, Instant, No Transcript, Refund
- Evidence text excerpt
- Link to enrollment page

### Deploy
```bash
# In D:\cb-core, ensure webapp/data/*.json files exist, then:
git add webapp/
git commit -m "webapp: update"
git push origin main
# Enable GitHub Pages → Source: main branch, /webapp folder (or /root)
```

---

## 4. Static JSON Exporter

### File
`D:\cb-core\scripts\export_webapp_data.py`

### Exports
| File | Query | Notes |
|------|-------|-------|
| `jobs.json` | Latest 500 by `id DESC` | title, company, url, sector, description, posted_at |
| `schools.json` | All 500, **sorted by `criteria_score DESC`** | includes `criteria_score` computed column |
| `companies.json` | Latest 500 by `id DESC` | company, careers_url, source, last_checked |
| `stats.json` | COUNT queries | jobs, companies, schools, channels, updated_at |

### criteria_score SQL
```sql
(no_id_verification::int + monthly_enrollment::int + instant_acceptance::int +
 no_transcript_required::int + monthly_refund::int + community_college::int)
 AS criteria_score
```

### Run (on VPS via cron)
```bash
0 * * * * cd /path/to/cb-core && python scripts/export_webapp_data.py
```

---

## 5. School Scraper

### File
`D:\cb-core\scripts\school_scraper.py`

### Filters searched
| Filter key | What it finds |
|------------|---------------|
| `best_match` | Schools meeting multiple criteria at once (run first) |
| `community_college` | Two-year / community colleges |
| `no_id_verification` | Enroll without government-issued ID |
| `no_transcript` | No transcript required |
| `monthly_enrollment` | Rolling/monthly intake |
| `instant_acceptance` | Same-day or immediate acceptance |
| `monthly_refund` | Pro-rated monthly refund schedule |

### Pipeline per school
```
Search query → Serper.dev API (or Gemini URL suggestion fallback)
  → For each result URL:
      fetch page text (BeautifulSoup, 6000 chars)
      find enrollment URL (regex + HEAD probe)
      analyze via Gemini 2.5-flash → JSON {criteria booleans + evidence}
      heuristic regex fallback if Gemini unavailable
      compute criteria_score (0–6)
      upsert to schools table (url_hash UNIQUE key)
```

### DB schema
```sql
CREATE TABLE schools (
    id                     SERIAL PRIMARY KEY,
    name                   TEXT NOT NULL,
    url                    TEXT,
    enrollment_url         TEXT,
    type                   TEXT,            -- "Community College" or "University/College"
    evidence               TEXT,            -- one-sentence summary of key criteria evidence
    no_id_verification     BOOLEAN DEFAULT FALSE,
    no_transcript_required BOOLEAN DEFAULT FALSE,
    monthly_enrollment     BOOLEAN DEFAULT FALSE,
    instant_acceptance     BOOLEAN DEFAULT FALSE,
    monthly_refund         BOOLEAN DEFAULT FALSE,
    community_college      BOOLEAN DEFAULT FALSE,
    filters                TEXT[],          -- GIN-indexed array of passing filter names
    source_query           TEXT,
    url_hash               TEXT UNIQUE,     -- MD5 of URL, prevents duplicates
    created_at             TIMESTAMPTZ DEFAULT NOW(),
    updated_at             TIMESTAMPTZ DEFAULT NOW()
);
```

### Priority ranking
Results sorted by `criteria_score` descending. Report tiers:
- 🏆 Score 6/6 — meets ALL criteria
- ⭐ Score 4-5 — excellent match
- ➡️ Score 1-3 — partial match

### Run
```bash
# Full run (best_match queries execute first):
py -3 D:\cb-core\scripts\school_scraper.py --filter all --report

# Single filter:
py -3 D:\cb-core\scripts\school_scraper.py --filter monthly_enrollment

# Custom query:
py -3 D:\cb-core\scripts\school_scraper.py --custom "open enrollment online college Kenya" --report
```

---

## 6. Deployment Checklist

### Prerequisites
```bash
pip install python-telegram-bot[job-queue]==22.7 psycopg2-binary requests \
            beautifulsoup4 playwright
playwright install chromium
```

### Step-by-step

1. **Create schools table** (one-time):
   ```bash
   py -3 -c "import sys; sys.path.insert(0,'D:/cb-core/scripts'); \
             import school_scraper; school_scraper.ensure_table()"
   ```

2. **Run school scraper**:
   ```bash
   py -3 D:\cb-core\scripts\school_scraper.py --filter all --report
   ```

3. **Export static JSON**:
   ```bash
   py -3 D:\cb-core\scripts\export_webapp_data.py
   ```

4. **Push webapp to GitHub Pages**:
   ```bash
   cd D:\cb-core
   git add webapp/
   git commit -m "webapp: initial deploy"
   git push origin main
   ```
   Then in GitHub repo settings → Pages → Source: `main` branch, `/webapp` folder.

5. **Start Telegram bot**:
   ```bash
   py -3 D:\cb-core\scripts\telegram_bot.py
   ```
   Or register as a Windows scheduled task / VPS systemd service.

6. **Set up cron for auto-export** (VPS):
   ```bash
   # Hourly export
   0 * * * * cd /path/to/cb-core && python scripts/export_webapp_data.py >> logs/export.log 2>&1
   # Daily school scrape
   0 3 * * * cd /path/to/cb-core && python scripts/school_scraper.py --filter all >> logs/scrape.log 2>&1
   ```

---

## 7. Environment Variables

All read from `D:\cb-core\.env`:

| Key | Used by |
|-----|---------|
| `GEMINI_API_KEY` | school_scraper, annotation_pipeline |
| `TELEGRAM_BOT_TOKEN` | telegram_bot |
| `TELEGRAM_ADMIN_CHAT_ID` | telegram_bot (admin gate) |
| `OPENROUTER_API_KEY` | LLM fallback |
| `SERPER_API_KEY` | school_scraper (web search) — optional |
| `REDIS_PORT` | health_daemon |

---

## 8. Data Flow

```
[School Scraper]          [Job Discovery / other scrapers]
     │                              │
     ▼                              ▼
[PostgreSQL: schools]    [PostgreSQL: jobs, discovered_platforms]
     │                              │
     └──────────┬───────────────────┘
                ▼
     [export_webapp_data.py]  (hourly cron)
                │
                ▼
     [webapp/data/*.json]  →  git push  →  GitHub Pages
                                              │
                                              ▼
                                    [Telegram WebApp button]
                                    → index.html reads JSON

[telegram_bot.py]
  ├── Polls DB every 5 min → pushes new jobs to admin chat
  ├── Polls DB every 10 min → pushes new schools
  ├── Daily digest at 08:00 Nairobi
  └── User commands → DB queries → formatted responses
```

---

## 9. Engineering Standards Applied

- **No mocks** — all DB queries hit real PostgreSQL; all web requests hit real URLs
- **Graceful degradation** — every DB/API call has a fallback (empty list / heuristic regex / synthetic annotations)
- **Idempotent writes** — school upsert uses `url_hash` UNIQUE key + `ON CONFLICT DO UPDATE`
- **Admin-only gate** — decorator pattern, applied per-function, fails closed
- **MarkdownV2 safety** — `_esc()` escapes all Telegram special chars before sending
- **Pagination everywhere** — jobs, schools, companies all support prev/next in both bot and web app
- **Criteria-first sorting** — schools meeting the most criteria always appear first across bot, webapp, and JSON export
- **No hardcoded secrets** — all credentials from `.env`, never in code
