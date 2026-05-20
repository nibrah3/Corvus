# start_mcps.ps1 — Start all CareerBridge MCP HTTP servers
# Run at boot via Task Scheduler (see register_startup.ps1)
# Each server auto-skips if already listening on its port.

$py  = "C:\Python314\python.exe"
$cb  = "E:\cb-core"

$servers = @(
    @{ mod = "humanizer_mcp.server"; port = 8701 },
    @{ mod = "capture_mcp.server";   port = 8702 },
    @{ mod = "uia_mcp.server";       port = 8703 },
    @{ mod = "browser_mcp.server";   port = 8704 },
    @{ mod = "gemini_mcp.server";    port = 8705 },
    @{ mod = "telegram_mcp.server";  port = 8706 },
    @{ mod = "answer_mcp.server";    port = 8707 },
    @{ mod = "sqlite_mcp.server";    port = 8708 },
    @{ mod = "memory_mcp.server";    port = 8709 }
)

foreach ($s in $servers) {
    $listening = (Get-NetTCPConnection -LocalPort $s.port -State Listen -ErrorAction SilentlyContinue) -ne $null
    if ($listening) {
        Write-Host "  SKIP  $($s.mod) (port $($s.port) already in use)"
    } else {
        Start-Process -FilePath $py `
            -ArgumentList "-m", $s.mod, "--http", "$($s.port)" `
            -WorkingDirectory $cb `
            -WindowStyle Hidden `
            -PassThru | Out-Null
        Start-Sleep -Milliseconds 500
        Write-Host "  START $($s.mod) -> http://localhost:$($s.port)/mcp"
    }
}

Write-Host ""
Write-Host "All MCP servers running."
