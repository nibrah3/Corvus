#!/bin/bash
# /opt/corvus/mcp_servers/start_mcps.sh
# Start all VPS CareerBridge MCP HTTP servers.
# Each server skips startup if its port is already listening.

# Load environment variables
set -a; source /opt/corvus/.env 2>/dev/null; set +a

PYTHON=/usr/bin/python3
MCP=/opt/corvus/mcp_servers
LOG=/opt/corvus/logs

mkdir -p "$LOG"

declare -A SERVERS=(
    ["postgres_mcp"]=8801
    ["crawlee_mcp"]=8802
    ["telegram_mcp"]=8803
)

for mod in "${!SERVERS[@]}"; do
    port=${SERVERS[$mod]}
    if ss -tlnp 2>/dev/null | grep -q ":$port "; then
        echo "  SKIP  $mod (port $port already listening)"
    else
        nohup $PYTHON -m "${mod}.server" --http "$port" \
            >> "$LOG/mcp_${mod}.log" 2>> "$LOG/mcp_${mod}.err" &
        sleep 0.5
        if ss -tlnp 2>/dev/null | grep -q ":$port "; then
            echo "  START $mod -> http://localhost:$port/mcp"
        else
            echo "  ERROR $mod failed to start on port $port (check $LOG/mcp_${mod}.err)"
        fi
    fi
done

echo ""
echo "VPS MCP servers done."
