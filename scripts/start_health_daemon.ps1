# start_health_daemon.ps1 — Launch health_daemon.py with user env vars explicitly loaded.
# Used by Task Scheduler (which may not inherit user-scope environment variables).

$env:TELEGRAM_BOT_TOKEN    = [System.Environment]::GetEnvironmentVariable("TELEGRAM_BOT_TOKEN",    "User")
$env:TELEGRAM_ADMIN_CHAT_ID = [System.Environment]::GetEnvironmentVariable("TELEGRAM_ADMIN_CHAT_ID", "User")

$py     = "C:\Python314\python.exe"
$script = "E:\cb-core\scripts\health_daemon.py"

& $py $script
