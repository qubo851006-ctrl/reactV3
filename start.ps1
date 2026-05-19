# ─────────────────────────────────────────────────────────────────
# V3 production-mode launcher
#
# Called from start.bat (double-clickable) but works standalone too:
#   powershell -ExecutionPolicy Bypass -File D:\prj\reactV3\start.ps1
#
# What it does:
#   1. Make sure logs/ exists
#   2. Check port 8001 isn't already taken — bail out if it is
#   3. Spawn uvicorn detached (no console window), redirect stdout/err
#      to dated log files under logs/
#   4. Wait 3 seconds, hit /api/health, print PASS/FAIL with where to
#      look if it failed
# ─────────────────────────────────────────────────────────────────
$ErrorActionPreference = 'Stop'

# Resolve project root from this script's location, so the file is
# relocatable (works whether it sits in D:\prj\reactV3 or anywhere else).
$root = Split-Path -Parent $MyInvocation.MyCommand.Path
$port = 8001

New-Item -ItemType Directory -Force -Path "$root\logs" | Out-Null

# Port-already-busy guard — refusing to start a duplicate prevents two
# uvicorns racing to bind 8001 and one of them crashing silently.
$existing = Get-NetTCPConnection -LocalPort $port -State Listen -ErrorAction SilentlyContinue
if ($existing) {
    $owner = $existing[0].OwningProcess
    Write-Host ""
    Write-Host "⚠  端口 $port 已被进程 PID $owner 占用" -ForegroundColor Yellow
    Write-Host "   若要先停掉再启:  Stop-Process -Id $owner -Force" -ForegroundColor Yellow
    Write-Host "   或直接跑 stop.bat 再 start.bat" -ForegroundColor Yellow
    Write-Host ""
    return
}

$stamp  = Get-Date -Format 'yyyyMMdd-HHmmss'
$logOut = "$root\logs\uvicorn-$stamp.log"
$logErr = "$root\logs\uvicorn-$stamp.err.log"

Write-Host ""
Write-Host "▶ 启动 V3 后端 (端口 $port,后台运行)..." -ForegroundColor Cyan
Start-Process python `
    -ArgumentList '-m', 'uvicorn', 'main:app', '--host', '0.0.0.0', '--port', $port, '--log-level', 'info' `
    -WorkingDirectory "$root\backend" `
    -RedirectStandardOutput $logOut `
    -RedirectStandardError $logErr `
    -WindowStyle Hidden

Start-Sleep -Seconds 3

# Health check — same logic the deploy-watch uses.
try {
    $r = Invoke-RestMethod "http://127.0.0.1:$port/api/health" -TimeoutSec 5
    Write-Host ""
    Write-Host "✅ V3 已启动 (status=$($r.status))" -ForegroundColor Green
    Write-Host "   URL:    http://localhost:$port" -ForegroundColor Green
    Write-Host "   日志:   $logOut" -ForegroundColor Gray
    Write-Host "   停止:   双击 stop.bat" -ForegroundColor Gray
    Write-Host ""
} catch {
    Write-Host ""
    Write-Host "❌ 健康检查失败,服务可能没启动成功" -ForegroundColor Red
    Write-Host "   错误日志: $logErr" -ForegroundColor Red
    Write-Host "   建议命令: Get-Content `"$logErr`" -Tail 30" -ForegroundColor Yellow
    Write-Host ""
}
