# CareerBridge Automated System Sweep — Local Machine

You are running a scheduled 30-minute health audit. No user is present.
Check every item in this manifest. Auto-fix simple issues. Send one Telegram
summary at the end via mcp__telegram__notify. Do not ask questions or wait for input.

---

## 1. MCP Servers — all ports must be listening on localhost

| Port | Server         |
|------|----------------|
| 8701 | humanizer_mcp  |
| 8702 | capture_mcp    |
| 8703 | uia_mcp        |
| 8704 | browser_mcp    |
| 8705 | gemini_mcp     |
| 8706 | telegram_mcp   |
| 8707 | answer_mcp     |
| 8708 | sqlite_mcp     |
| 8709 | memory_mcp     |
| 8710 | dom_mcp        |
| 8712 | cdp_mcp        |
| 8713 | vps_mcp        |
| 8714 | schools_mcp    |

Check (PowerShell): `Get-NetTCPConnection -LocalPort {port} -State Listen -ErrorAction SilentlyContinue`
Auto-fix if any are missing: `powershell -NonInteractive -File D:\cb-core\scripts\start_mcps.ps1 -Force`

---

## 2. SSH Tunnel — local ports must be open (forwarded to VPS)

| Local Port | Tunnels to  |
|-----------|-------------|
| 6380      | VPS Redis   |
| 5433      | VPS Postgres|
| 3101      | VPS Crawlee |
| 7788      | VPS Firecrawl|

Check (PowerShell): `(New-Object System.Net.Sockets.TcpClient).Connect('127.0.0.1', {port})`
If tunnel is down the CareerBridge-Tunnel task auto-reconnects, but alert Telegram.

---

## 3. Windows Task Scheduler — all must exist and be Running or Ready

| Task Name                     | Expected Status      |
|-------------------------------|----------------------|
| \CareerBridge-Agent           | Running              |
| \CareerBridge-Health          | Running              |
| \CareerBridge-Tunnel          | Running              |
| \CareerBridge_SchoolReport_6h | Ready or Running     |
| \CareerBridge_Sweep           | Ready or Running     |
| \CareerBridge_Gate            | Ready or Running     |

Check: `schtasks /query /fo LIST /nh /tn "{task}" 2>&1`
Auto-fix stopped task: `schtasks /run /tn "{task}"`

---

## 4. VPS Crontab — connect via SSH and verify all entries exist

SSH: `ssh -i C:\Users\HP\.ssh\cb_tunnel -o StrictHostKeyChecking=no -o ConnectTimeout=10 root@77.42.91.185 crontab -l`

Every one of these lines MUST be present in the output:

```
*/5 * * * * /opt/corvus/scripts/vps-status-sync.sh
*/30 * * * * /opt/corvus/scripts/run_sweep.sh
0 5 * * * /opt/corvus/scripts/discover_all.sh
0 6 * * * cd /opt/corvus && python3 corvus_discovery.py discovery
0 */6 * * * /opt/corvus/scripts/discover_tier1.sh
0 7,19 * * * curl -sf -X POST http://localhost:3100/scrape/reddit -H 'Content-Type: application/json' -d '{"limit":50}' -o /tmp/reddit_result.json && python3 /opt/corvus/scripts/discover_and_queue.py
0 8 * * * cd /opt/corvus && python3 scripts/serper_graph_expand.py
0 9 * * 1 cd /opt/corvus && python3 scripts/status_cache_updater.py
```

If any are missing: SSH in and restore the full crontab. Alert Telegram for each missing entry.

---

## 5. VPS Service Health — check via mcp__vps__get_system_status

Alert conditions:
- `redis` != "ok"      → "VPS Redis is DOWN"
- `postgres` != "ok"   → "VPS Postgres is DOWN"
- `failed` > 10        → "{n} failed jobs need attention"
- `pending` > 8000     → "Queue backed up: {n} pending"

---

## 6. Log File Errors — check last 30 minutes

Scan last 100 lines of each file for ERROR or CRITICAL:
- `D:\cb-core\logs\school_cron.log`
- `D:\cb-core\logs\sweep.log`

Alert Telegram if any ERROR/CRITICAL found in the last 30 minutes.

---

## 7. VPS Discovery Freshness — check via SSH

Run: `ssh ... "stat -c %Y /var/log/discovery-daily.log 2>/dev/null || echo 0"`
If the daily discovery log hasn't been modified in 26+ hours, alert: "Discovery hasn't run in 26h."

Run: `ssh ... "tail -5 /var/log/discovery-daily.log 2>/dev/null"`
If the last line contains "error" or "fail", alert.

---

## Telegram Summary Rules

Send ONE message at the end. Format:
- All green: `✅ Sweep clear — {HH:MM}`
- Issues: `⚠️ Sweep {HH:MM}\n• {issue1}\n• {issue2}` (max 5 bullets, one line each)

Only send the green message if you made at least one auto-fix this run.
If everything was already fine and you changed nothing, skip the Telegram message entirely.
