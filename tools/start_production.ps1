<#
.SYNOPSIS
    Start the V3 backend + frontend in production mode (no --reload).

.DESCRIPTION
    Designed for unattended startup on Windows. Logs to D:/claude/reactV3/logs/
    so you can tail them without keeping the launch window open.

    For true auto-start on boot, wrap this with nssm:
        nssm install reactV3-backend  powershell -File D:\claude\reactV3\tools\start_production.ps1 -BackendOnly
        nssm install reactV3-frontend powershell -File D:\claude\reactV3\tools\start_production.ps1 -FrontendOnly

.PARAMETER BackendOnly
    Start only the FastAPI/uvicorn backend on port 8000.

.PARAMETER FrontendOnly
    Start only the built frontend (vite preview) on port 5173.

.PARAMETER Port
    Backend port. Default 8000.

.EXAMPLE
    .\tools\start_production.ps1                    # both, foreground
    .\tools\start_production.ps1 -BackendOnly       # backend only
#>
[CmdletBinding()]
param(
    [switch]$BackendOnly,
    [switch]$FrontendOnly,
    [int]$Port = 8000
)

$ErrorActionPreference = 'Stop'
$Root = Split-Path -Parent $PSScriptRoot
$LogDir = Join-Path $Root 'logs'
New-Item -ItemType Directory -Force -Path $LogDir | Out-Null

$Stamp = Get-Date -Format 'yyyyMMdd-HHmmss'

function Start-Backend {
    $log = Join-Path $LogDir "backend-$Stamp.log"
    Write-Host "[backend] starting on :$Port, logging to $log"
    Push-Location (Join-Path $Root 'backend')
    try {
        # Production: NO --reload (would respawn on every trace write since
        # WatchFiles sees our log_config touching files), NO --host 0.0.0.0
        # unless you're behind a firewall or reverse proxy. Adjust as needed.
        Start-Process -FilePath 'python' `
            -ArgumentList @('-m', 'uvicorn', 'main:app', '--host', '127.0.0.1', '--port', $Port, '--log-level', 'info') `
            -RedirectStandardOutput $log `
            -RedirectStandardError "$log.err" `
            -NoNewWindow
    }
    finally { Pop-Location }
}

function Start-Frontend {
    $log = Join-Path $LogDir "frontend-$Stamp.log"
    Write-Host "[frontend] building + previewing on :5173, logging to $log"
    Push-Location (Join-Path $Root 'frontend')
    try {
        # Build once to keep the served bundle in sync with the repo state.
        & npm run build *>&1 | Tee-Object -FilePath "$log.build" | Out-Null
        Start-Process -FilePath 'npm' `
            -ArgumentList @('run', 'preview', '--', '--port', '5173') `
            -RedirectStandardOutput $log `
            -RedirectStandardError "$log.err" `
            -NoNewWindow
    }
    finally { Pop-Location }
}

if ($BackendOnly) { Start-Backend; return }
if ($FrontendOnly) { Start-Frontend; return }

Start-Backend
Start-Sleep -Seconds 3
Start-Frontend

Write-Host ''
Write-Host '─────────────────────────────────────────────────────────'
Write-Host "  V3 running"
Write-Host "  Backend : http://127.0.0.1:$Port"
Write-Host '  Frontend: http://127.0.0.1:5173'
Write-Host "  Logs    : $LogDir\*-$Stamp.log"
Write-Host '─────────────────────────────────────────────────────────'
