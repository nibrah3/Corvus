#!/bin/bash
# run_sweep.sh — CareerBridge VPS 30-min health sweep (bash, no Claude auth needed)

LOG=/var/log/corvus-sweep.log
ENV_FILE=/opt/corvus/.env
ISSUES=()
FIXES=()

log() { echo "[$(date -u +%Y-%m-%dT%H:%M:%SZ)] $*" >> "$LOG"; }
log "=== VPS Sweep starting ==="

# Load env
if [ -f "$ENV_FILE" ]; then
    set -o allexport; source "$ENV_FILE"; set +o allexport
fi

TG_TOKEN=${TELEGRAM_BOT_TOKEN:-}
TG_CHAT=${TELEGRAM_ADMIN_CHAT_ID:-}

tg_send() {
    local msg="$1"
    [ -z "$TG_TOKEN" ] && return
    curl -s -X POST "https://api.telegram.org/bot${TG_TOKEN}/sendMessage" \
        --data-urlencode "chat_id=${TG_CHAT}" \
        --data-urlencode "text=${msg}" \
        -o /dev/null 2>/dev/null || true
}

redis_ok() {
    python3 - <<'PYEOF' 2>/dev/null
import socket
s = socket.create_connection(('localhost', 6379), 2)
s.sendall(b"PING\r\n")
r = s.recv(10)
s.close()
exit(0 if b"PONG" in r else 1)
PYEOF
}

# ── 1. Redis ──────────────────────────────────────────────────────────────────
if redis_ok; then
    log "Redis: OK"
else
    log "Redis: FAIL — attempting restart"
    systemctl restart redis 2>/dev/null || systemctl restart redis-server 2>/dev/null || true
    sleep 3
    if redis_ok; then
        FIXES+=("Redis was down — restarted successfully")
        log "Redis: restarted OK"
    else
        ISSUES+=("Redis still DOWN after restart")
        log "Redis: still DOWN"
    fi
fi

# ── 2. Postgres ───────────────────────────────────────────────────────────────
if python3 -c "
import psycopg2, os
conn = psycopg2.connect('postgresql://corvus:corvus-local-password@localhost:5432/careerbridge', connect_timeout=5)
conn.close()
" 2>/dev/null; then
    log "Postgres: OK"
else
    ISSUES+=("Postgres is DOWN")
    log "Postgres: FAIL"
fi

# ── 3. Crawlee ────────────────────────────────────────────────────────────────
if curl -sf --max-time 5 http://localhost:3100/health -o /dev/null 2>/dev/null; then
    log "Crawlee: OK"
else
    ISSUES+=("Crawlee API is DOWN at :3100")
    log "Crawlee: FAIL"
fi

# ── 4. Firecrawl ──────────────────────────────────────────────────────────────
if curl -sf --max-time 5 http://localhost:7788/ -o /dev/null 2>/dev/null; then
    log "Firecrawl: OK"
else
    log "Firecrawl: FAIL — attempting docker restart"
    docker restart corvus-firecrawl 2>/dev/null || true
    sleep 5
    if curl -sf --max-time 5 http://localhost:7788/ -o /dev/null 2>/dev/null; then
        FIXES+=("Firecrawl was down — restarted container")
        log "Firecrawl: restarted OK"
    else
        ISSUES+=("Firecrawl still DOWN after restart")
        log "Firecrawl: still DOWN"
    fi
fi

# ── 5. Crontab manifest ───────────────────────────────────────────────────────
CRONTAB=$(crontab -l 2>/dev/null || echo "")
EXPECTED=(
    "vps-status-sync.sh"
    "run_sweep.sh"
    "discover_all.sh"
    "corvus_discovery.py discovery"
    "discover_tier1.sh"
    "scrape/reddit"
    "serper_graph_expand.py"
    "status_cache_updater.py"
)
MISSING_CRONS=()
for entry in "${EXPECTED[@]}"; do
    if ! echo "$CRONTAB" | grep -qF "$entry"; then
        MISSING_CRONS+=("$entry")
        log "Cron MISSING: $entry"
    fi
done

if [ ${#MISSING_CRONS[@]} -gt 0 ]; then
    log "Restoring full crontab..."
    cat > /tmp/restored_crontab.txt << 'CRONEOF'
*/5 * * * * /opt/corvus/scripts/vps-status-sync.sh >> /var/log/vps-status-sync.log 2>&1
*/30 * * * * /opt/corvus/scripts/run_sweep.sh >> /var/log/corvus-sweep.log 2>&1
0 5 * * * /opt/corvus/scripts/discover_all.sh >> /var/log/discovery-daily.log 2>&1
0 6 * * * cd /opt/corvus && python3 corvus_discovery.py discovery >> /var/log/discovery-apify.log 2>&1
0 */6 * * * /opt/corvus/scripts/discover_tier1.sh >> /var/log/discovery-tier1.log 2>&1
0 7,19 * * * curl -sf -X POST http://localhost:3100/scrape/reddit -H 'Content-Type: application/json' -d '{"limit":50}' -o /tmp/reddit_result.json && cd /opt/corvus && python3 scripts/discover_and_queue.py >> /var/log/discovery-reddit.log 2>&1
0 8 * * * cd /opt/corvus && python3 scripts/serper_graph_expand.py >> /var/log/discovery-serp.log 2>&1
0 9 * * 1 cd /opt/corvus && python3 scripts/status_cache_updater.py >> /var/log/weekly-summary.log 2>&1
CRONEOF
    crontab /tmp/restored_crontab.txt
    FIXES+=("Restored ${#MISSING_CRONS[@]} missing cron job(s): ${MISSING_CRONS[*]}")
    log "Crontab restored"
fi

# ── 6. Discovery log freshness ────────────────────────────────────────────────
check_log_age() {
    local file="$1" max_minutes="$2" label="$3"
    if [ -f "$file" ]; then
        age_minutes=$(( ( $(date +%s) - $(stat -c %Y "$file") ) / 60 ))
        if [ "$age_minutes" -gt "$max_minutes" ]; then
            ISSUES+=("${label} log stale: ${age_minutes}m since last run")
            log "${label}: stale (${age_minutes}m)"
        else
            log "${label}: fresh (${age_minutes}m ago)"
        fi
    fi
}
check_log_age /var/log/discovery-daily.log  1560 "Daily discovery"
check_log_age /var/log/discovery-tier1.log   420 "Tier1 discovery"
check_log_age /var/log/discovery-reddit.log  780 "Reddit discovery"

# ── 7. Job queue depth ────────────────────────────────────────────────────────
PENDING=$(python3 - 2>/dev/null << 'PYEOF'
import socket
try:
    s = socket.create_connection(('localhost', 6379), 2)
    s.sendall(b"*2\r\n$4\r\nLLEN\r\n$24\r\ncorvus:pending_approvals\r\n")
    resp = s.recv(128).decode()
    s.close()
    print(resp.split('\r\n')[0].lstrip(':'))
except Exception:
    print('0')
PYEOF
)
PENDING=${PENDING:-0}
if [ "$PENDING" -gt 8000 ] 2>/dev/null; then
    ISSUES+=("Queue backed up: ${PENDING} pending approvals")
fi
log "Queue depth: ${PENDING}"

# ── Send Telegram summary ─────────────────────────────────────────────────────
HOUR=$(date -u +%H:%M)
if [ ${#ISSUES[@]} -gt 0 ] || [ ${#FIXES[@]} -gt 0 ]; then
    MSG="VPS sweep ${HOUR}"
    for fix in "${FIXES[@]}"; do MSG="${MSG}\n- Fixed: ${fix}"; done
    for issue in "${ISSUES[@]}"; do MSG="${MSG}\n- Issue: ${issue}"; done
    tg_send "$MSG"
    log "Telegram sent: ${#FIXES[@]} fixes, ${#ISSUES[@]} issues"
else
    log "All clear — no Telegram needed"
fi

log "=== VPS Sweep complete ==="
