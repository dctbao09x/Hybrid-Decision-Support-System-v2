# deploy_server.ps1
# ===================
# Production deployment script for Windows
# Uses Uvicorn multi-worker mode (gunicorn not supported on Windows)
#
# Usage:
#   .\scripts\deploy_server.ps1 -Workers 8 -Port 8000
#

param(
    [int]$Workers = 8,
    [int]$Port = 8000,
    [string]$Host = "0.0.0.0",
    [int]$Timeout = 30,
    [int]$Backlog = 2048,
    [switch]$Reload,
    [string]$LogLevel = "info"
)

$ErrorActionPreference = "Stop"

Write-Host "=" * 60 -ForegroundColor Cyan
Write-Host "HDSS API SERVER DEPLOYMENT" -ForegroundColor Cyan
Write-Host "=" * 60 -ForegroundColor Cyan

# Environment
$env:ENVIRONMENT = "production"
$env:HTTP_MAX_CONNECTIONS = "200"
$env:HTTP_MAX_PER_HOST = "50"
$env:HTTP_KEEPALIVE = "30"
$env:DB_POOL_SIZE = "20"
$env:DB_MAX_OVERFLOW = "30"

Write-Host ""
Write-Host "[Config]" -ForegroundColor Yellow
Write-Host "  Workers: $Workers"
Write-Host "  Host: ${Host}:${Port}"
Write-Host "  Timeout: ${Timeout}s"
Write-Host "  Backlog: $Backlog"
Write-Host "  Reload: $Reload"
Write-Host "  Log Level: $LogLevel"

# Kill existing processes on port
Write-Host ""
Write-Host "[Cleanup] Stopping existing processes on port $Port..." -ForegroundColor Yellow

$pids = netstat -ano | Select-String ":$Port.*LISTEN" | ForEach-Object {
    ($_ -split '\s+')[-1]
} | Sort-Object -Unique

foreach ($pid in $pids) {
    if ($pid -and $pid -ne "0") {
        Write-Host "  Killing PID $pid"
        Stop-Process -Id $pid -Force -ErrorAction SilentlyContinue
    }
}

Start-Sleep -Seconds 2

# Build command
$uvicornArgs = @(
    "-m", "uvicorn",
    "backend.run_api:app",
    "--host", $Host,
    "--port", $Port,
    "--workers", $Workers,
    "--timeout-keep-alive", $Timeout,
    "--backlog", $Backlog,
    "--log-level", $LogLevel,
    "--no-access-log"
)

if ($Reload) {
    $uvicornArgs += "--reload"
}

Write-Host ""
Write-Host "[Starting] python $($uvicornArgs -join ' ')" -ForegroundColor Green
Write-Host ""

# Start server
Set-Location $PSScriptRoot\..

try {
    & python @uvicornArgs
}
catch {
    Write-Host "Error: $_" -ForegroundColor Red
    exit 1
}
