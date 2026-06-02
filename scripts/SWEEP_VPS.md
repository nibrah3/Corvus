# CareerBridge Automated System Sweep — VPS

You are running a scheduled 30-minute health audit on the VPS. No user is present.
Use bash commands to check each item. Send Telegram alerts via curl when issues are found.
Auto-fix simple issues. Do not ask questions or wait for input.

Telegram bot: load token and chat_id from /opt/corvus/.env (TELEGRAM_BOT_TOKEN, TELEGRAM_ADMIN_CHAT_ID).
Send alert: `curl -s -X POST "https://api.telegram.org/bot${TOKEN}/sendMessage" -d chat_id=${CHAT_ID} -d text="..."`

---

## 1. Redis — must respond to PING

Check: `redis-cli -p 6379 ping`
Expected: PONG
Fix: `systemctl restart redis`
Alert: "VPS Redis is DOWN — restarted"

---

## 2. Postgres — must accept connections

Check: `psql postgresql://corvus:corvus-local-password@localhost:5432/careerbridge -c "SELECT 1" -t 2>&1`
Expected: output contains "1"
Fix: `systemctl restart postgresql`
Alert: "VPS Postgres is DOWN"

---

## 3. Crawlee API — must respond

Check: `curl -sf http://localhost:3100/health 2>/dev/null || curl -sf http://localhost:3100/ 2>/dev/null`
Expected: HTTP 200 response
Alert if down: "VPS Crawlee API is DOWN at :3100"

---

## 4. Firecrawl — must respond

Check: `curl -sf http://localhost:7788/v1/health 2>/dev/null || curl -sf --max-time 5 http://localhost:7788/ 2>/dev/null`
Expected: HTTP response (any 2xx)
Alert if down: "VPS Firecrawl is DOWN at :7788"

---

## 5. Crontab Manifest — every entry must be present

Run: `crontab -l`

Every one of these lines MUST appear (check each substring):

| Must contain                          | Description              |
|---------------------------------------|--------------------------|
| `vps-status-sync.sh`                  | 5-min status sync        |
| `run_sweep.sh`                        | 30-min VPS sweep         |
| `discover_all.sh`                     | Daily 5 AM full discover |
| `corvus_discovery.py discovery`       | 6 AM Apify/Serper        |
| `discover_tier1.sh`                   | Every-6h ATS polling     |
| `scrape/reddit`                       | 7 AM & 7 PM Reddit       |
| `serper_graph_expand.py`              | 8 AM SERP keywords       |
| `status_cache_updater.py`             | Mon 9 AM weekly summary  |

If any are missing, restore the full crontab (see expected crontab below) and alert.

Expected full crontab:
```
*/5 * * * * /opt/corvus/scripts/vps-status-sync.sh >> /var/log/vps-status-sync.log 2>&1
*/30 * * * * /opt/corvus/scripts/run_sweep.sh >> /var/log/corvus-sweep.log 2>&1
0 5 * * * /opt/corvus/scripts/discover_all.sh >> /var/log/discovery-daily.log 2>&1
0 6 * * * cd /opt/corvus && python3 corvus_discovery.py discovery >> /var/log/discovery-apify.log 2>&1
0 */6 * * * /opt/corvus/scripts/discover_tier1.sh >> /var/log/discovery-tier1.log 2>&1
0 7,19 * * * curl -sf -X POST http://localhost:3100/scrape/reddit -H 'Content-Type: application/json' -d '{"limit":50}' -o /tmp/reddit_result.json && python3 /opt/corvus/scripts/discover_and_queue.py >> /var/log/discovery-reddit.log 2>&1
0 8 * * * cd /opt/corvus && python3 scripts/serper_graph_expand.py >> /var/log/discovery-serp.log 2>&1
0 9 * * 1 cd /opt/corvus && python3 scripts/status_cache_updater.py >> /var/log/weekly-summary.log 2>&1
```

---

## 6. Discovery Log Freshness

Check last modified time of key logs:
- `/var/log/discovery-daily.log` — should be modified within 26 hours
- `/var/log/discovery-tier1.log` — should be modified within 7 hours
- `/var/log/discovery-reddit.log` — should be modified within 13 hours

Command: `find /var/log -name "discovery-*.log" -mmin +{minutes} 2>/dev/null`
Alert: "Discovery log stale: {filename} — last run too long ago"

Also check last line of each log for "error" or "fail" (case-insensitive):
`tail -3 /var/log/discovery-daily.log 2>/dev/null`

---

## 7. Job Queue Depth

Check: `redis-cli -p 6379 llen corvus:pending_approvals`
Alert if > 8000: "Queue backed up: {n} pending approvals on VPS"

Check failed count in Postgres:
`psql postgresql://corvus:corvus-local-password@localhost:5432/careerbridge -c "SELECT status, count(*) FROM jobs GROUP BY status" -t 2>/dev/null`
Alert if failed > 10: "{n} failed jobs in Postgres"

---

## Telegram Summary Rules

Load token and chat_id from /opt/corvus/.env.
Send ONE message at end. Format:
- All green: `✅ VPS sweep clear — {HH:MM UTC}`
- Issues found: `⚠️ VPS sweep {HH:MM}\n• {issue1}\n• {issue2}` (max 5 bullets)

Only send the green message if you made an auto-fix this run.
Skip entirely if everything was already healthy and you changed nothing.
