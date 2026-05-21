# setup_new_machine.ps1 — Bootstrap CareerBridge on a fresh Windows machine.
# Run as Administrator from any PowerShell prompt.
#
# What this does:
#   1. Detects clone path (D:\cb-core or prompts)
#   2. Installs all pip dependencies
#   3. Creates required directories (profiles/, logs/)
#   4. Applies DB schema if careerbridge.db is missing
#   5. Sets required environment variables (prompts interactively if not already set)
#   6. Registers Task Scheduler startup tasks
#
# After this script finishes, reboot or run start_agent.ps1 manually.

$ErrorActionPreference = "Stop"

# ── 1. Locate the clone ───────────────────────────────────────────────────────

$cb = $PSScriptRoot | Split-Path -Parent
Write-Host "CB root: $cb"

# ── 2. Python ─────────────────────────────────────────────────────────────────

$py = "C:\Python314\python.exe"
if (-not (Test-Path $py)) {
    Write-Host "ERROR: Python not found at $py. Install Python 3.14 first." -ForegroundColor Red
    exit 1
}
Write-Host "Python: $py"

# ── 3. Pip install ────────────────────────────────────────────────────────────

Write-Host ""
Write-Host "Installing pip dependencies..."
& $py -m pip install -r "$cb\requirements.txt" --quiet
if ($LASTEXITCODE -ne 0) {
    Write-Host "WARNING: pip install had errors — check output above." -ForegroundColor Yellow
}

# ── 4. Directories ────────────────────────────────────────────────────────────

@("$cb\profiles", "$cb\logs", "$cb\runtime") | ForEach-Object {
    if (-not (Test-Path $_)) {
        New-Item -ItemType Directory -Path $_ | Out-Null
        Write-Host "Created: $_"
    }
}

# ── 5. DB schema ──────────────────────────────────────────────────────────────

$db = "$cb\careerbridge.db"
if (-not (Test-Path $db)) {
    Write-Host "Applying database schema..."
    & $py -c "
import sqlite3, pathlib
schema = pathlib.Path(r'$cb\docs\schema.sql').read_text()
with sqlite3.connect(r'$db') as conn:
    conn.executescript(schema)
print('DB created.')
"
}

# ── 6. Environment variables ──────────────────────────────────────────────────

function Set-UserEnvIfMissing($name, $prompt) {
    $existing = [System.Environment]::GetEnvironmentVariable($name, "User")
    if (-not $existing) {
        $val = Read-Host "$prompt"
        if ($val) {
            [System.Environment]::SetEnvironmentVariable($name, $val, "User")
            Write-Host "  Set $name"
        } else {
            Write-Host "  Skipped $name (empty)" -ForegroundColor Yellow
        }
    } else {
        Write-Host "  $name already set"
    }
}

Write-Host ""
Write-Host "Checking environment variables..."
Set-UserEnvIfMissing "OPENROUTER_API_KEY"      "Enter OPENROUTER_API_KEY"
Set-UserEnvIfMissing "TELEGRAM_BOT_TOKEN"      "Enter TELEGRAM_BOT_TOKEN"
Set-UserEnvIfMissing "TELEGRAM_ADMIN_CHAT_ID"  "Enter TELEGRAM_ADMIN_CHAT_ID"
Set-UserEnvIfMissing "GEMINI_API_KEY"          "Enter GEMINI_API_KEY"

# Convenience: set CB_DIR so health_daemon.py auto-detects the right path
[System.Environment]::SetEnvironmentVariable("CB_DIR", $cb, "User")
Write-Host "  CB_DIR = $cb"

# ── 7. Task Scheduler ─────────────────────────────────────────────────────────

Write-Host ""
Write-Host "Registering startup tasks (requires Administrator)..."
try {
    & "$cb\scripts\register_startup.ps1"
} catch {
    Write-Host "WARNING: Task Scheduler registration failed: $_" -ForegroundColor Yellow
    Write-Host "Run register_startup.ps1 manually as Administrator."
}

# ── Done ──────────────────────────────────────────────────────────────────────

Write-Host ""
Write-Host "Setup complete." -ForegroundColor Green
Write-Host ""
Write-Host "Next steps:"
Write-Host "  1. Load Chrome extension (unpacked) from: $cb\dom_mcp\extension\"
Write-Host "  2. Start agent now: powershell -File $cb\scripts\start_agent.ps1"
Write-Host "  3. Or reboot to auto-start via Task Scheduler."
