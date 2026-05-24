# start_health_daemon.ps1 — Launch health_daemon.py with env vars loaded.
# Priority: .env file first (most portable), then User-scope env vars as fallback.
# Used by Task Scheduler (which may not inherit user-scope environment variables).

$cb      = Split-Path $PSScriptRoot -Parent
$envFile = Join-Path $cb ".env"

# Load all vars from .env first
if (Test-Path $envFile) {
    Get-Content $envFile | ForEach-Object {
        if ($_ -match '^([^#=\s][^=]*)=(.*)$') {
            $k = $Matches[1].Trim(); $v = $Matches[2].Trim()
            [System.Environment]::SetEnvironmentVariable($k, $v)
        }
    }
}

# Override with User-scope env vars if they exist (allows per-machine overrides)
foreach ($var in @("TELEGRAM_BOT_TOKEN", "TELEGRAM_ADMIN_CHAT_ID", "OPENROUTER_API_KEY", "GEMINI_API_KEY")) {
    $userVal = [System.Environment]::GetEnvironmentVariable($var, "User")
    if ($userVal) { [System.Environment]::SetEnvironmentVariable($var, $userVal) }
}

$py     = "C:\Python314\python.exe"
$script = "$PSScriptRoot\health_daemon.py"

& $py $script
