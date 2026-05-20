# Caddy 后台启动脚本 — V3 HTTPS 反向代理
# 用法:powershell.exe -NoProfile -ExecutionPolicy Bypass -File caddy-start.ps1
# 或者直接双击 start-https.bat

$ErrorActionPreference = 'Continue'

$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$Caddyfile = Join-Path $ScriptDir 'Caddyfile'
$LogDir    = Join-Path $ScriptDir 'logs'
$CaddyExe  = 'D:\tools\caddy.exe'

# Caddy 二进制存在?
if (-not (Test-Path $CaddyExe)) {
    Write-Error "[caddy-start] caddy.exe not found at $CaddyExe — install per docs/DEPLOY-HTTPS.md"
    exit 1
}

# Caddyfile 存在?
if (-not (Test-Path $Caddyfile)) {
    Write-Error "[caddy-start] Caddyfile not found at $Caddyfile"
    exit 1
}

# Already running? skip (avoid double-launch)
$existing = Get-Process -Name caddy -ErrorAction SilentlyContinue
if ($existing) {
    Write-Host "[caddy-start] caddy.exe already running (PID $($existing.Id)), skip"
    exit 0
}

# Ensure log dir exists
if (-not (Test-Path $LogDir)) {
    New-Item -ItemType Directory -Force -Path $LogDir | Out-Null
}

# Unique log filenames (timestamp + random suffix) — avoid same-second collisions
# when start-https.bat is double-invoked or schedtask retries
$stamp   = Get-Date -Format 'yyyyMMdd-HHmmss'
$suffix  = [System.IO.Path]::GetRandomFileName().Substring(0,4)
$logOut  = Join-Path $LogDir "caddy-$stamp-$suffix.log"
$logErr  = Join-Path $LogDir "caddy-$stamp-$suffix.err.log"

try {
    $proc = Start-Process `
        -FilePath $CaddyExe `
        -ArgumentList @('run', '--config', $Caddyfile) `
        -WorkingDirectory $ScriptDir `
        -WindowStyle Hidden `
        -RedirectStandardOutput $logOut `
        -RedirectStandardError  $logErr `
        -PassThru `
        -ErrorAction Stop
    Write-Host "[caddy-start] started PID $($proc.Id)"
    Write-Host "[caddy-start] stdout: $logOut"
    Write-Host "[caddy-start] stderr: $logErr"
    exit 0
} catch {
    Write-Error "[caddy-start] failed: $_"
    exit 1
}
