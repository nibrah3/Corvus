#!/bin/bash
# vps_claude_login.sh — One-time Claude Code OAuth login on headless VPS.
#
# Uses Xvfb virtual display + Chromium to complete the browser-based
# OAuth flow for Claude Code subscription (no API key needed).
#
# Run ONCE as root on the VPS:
#   bash /opt/corvus/vps_claude_login.sh
#
# After successful login, the token is stored in ~/.claude/ and persists.
# Xvfb/Chromium can be killed after login completes.

set -e

DISPLAY_NUM=:99
export DISPLAY=$DISPLAY_NUM

echo "=== Claude Code VPS Login ==="
echo "Starting virtual display..."
Xvfb $DISPLAY_NUM -screen 0 1280x800x24 -ac &
XVFB_PID=$!
sleep 2

echo "Starting Chromium in background..."
CHROMIUM=$(which chromium-browser 2>/dev/null || which chromium 2>/dev/null)
if [ -z "$CHROMIUM" ]; then
    echo "ERROR: chromium-browser not found. Run: apt-get install -y chromium-browser"
    kill $XVFB_PID 2>/dev/null
    exit 1
fi

$CHROMIUM \
    --no-sandbox \
    --disable-gpu \
    --disable-dev-shm-usage \
    --disable-setuid-sandbox \
    --display=$DISPLAY_NUM \
    &
CHROMIUM_PID=$!
sleep 2

echo ""
echo "Running: claude /login"
echo "Watch the Chromium window (if you have a VNC viewer) OR"
echo "copy the URL printed below and open it on your phone/desktop to complete OAuth."
echo ""

# claude /login will print a URL to visit — copy it to your browser
claude /login

echo ""
echo "Login complete. Killing virtual display..."
kill $CHROMIUM_PID 2>/dev/null || true
kill $XVFB_PID 2>/dev/null || true

echo ""
echo "Verifying login..."
claude --print "Reply with just: login OK" --dangerously-skip-permissions 2>&1 | tail -3
echo ""
echo "Done. Token stored in ~/.claude/ — persists across reboots."
