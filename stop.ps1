# ─────────────────────────────────────────────────────────────────
# V3 stopper — finds whoever's holding port 8001 and kills them.
#
# Won't touch V2 on port 8000, since we look up by port not by
# process name.
# ─────────────────────────────────────────────────────────────────
$ErrorActionPreference = 'Stop'
$port = 8001

$conn = Get-NetTCPConnection -LocalPort $port -State Listen -ErrorAction SilentlyContinue
if (-not $conn) {
    Write-Host ""
    Write-Host "ℹ  端口 $port 当前无监听 — V3 后端没在跑" -ForegroundColor Gray
    Write-Host ""
    return
}

$procId = $conn[0].OwningProcess
$proc = Get-Process -Id $procId -ErrorAction SilentlyContinue
$name = if ($proc) { $proc.ProcessName } else { 'unknown' }

Write-Host ""
Write-Host "▶ 停止 V3 后端 (PID $procId, $name)..." -ForegroundColor Cyan
Stop-Process -Id $procId -Force
Start-Sleep -Seconds 1

# Confirm
$still = Get-NetTCPConnection -LocalPort $port -State Listen -ErrorAction SilentlyContinue
if ($still) {
    Write-Host "⚠  PID $procId 还没退出,可能被父进程拉起。再试一次或重启系统" -ForegroundColor Yellow
} else {
    Write-Host "✅ 已停止" -ForegroundColor Green
}
Write-Host ""
