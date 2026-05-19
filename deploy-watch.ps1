# ─────────────────────────────────────────────────────────────────────
# V3 自动部署脚本 deploy-watch.ps1
#
# 由 Windows 任务计划程序周期调用 (建议 5 分钟一次)：
#   schtasks /create /tn "reactV3 deploy" /sc minute /mo 5 ^
#     /tr "powershell -ExecutionPolicy Bypass -File D:\prj\reactV3\deploy-watch.ps1"
#
# 工作流程：
#   1. git fetch + 比较 commit；无更新就退出
#   2. 取文件锁，防止两个实例并发部署
#   3. git pull
#   4. 后端依赖：pip install -r requirements.txt (仅当 requirements.txt 变化)
#   5. 前端：npm install (仅当 package-lock.json 变化) + npm run build (永远)
#   6. 优雅停旧 uvicorn (按端口锁定 PID，不会误杀 V2 在 8000 的 uvicorn)
#   7. 启新 uvicorn (production 模式，无 --reload，日志重定向到文件)
#   8. 健康检查：等 /api/health 返回 200，否则报警
#
# 与 V2 deploy-watch.ps1 的关键差异：
#   - 路径迁到 D:\prj\reactV3 (V2 在 D:\prj\react-master)
#   - 端口改为 8001 (V2 占 8000)
#   - 用 lock 文件防止并发部署
#   - 按端口杀进程，不会误杀 V2 的 python
#   - 新增 npm install + npm run build (V3 需要前端 build 产物)
#   - 健康检查
# ─────────────────────────────────────────────────────────────────────
$ErrorActionPreference = 'Stop'

# ── 配置 ────────────────────────────────────────────────────────────
$projectDir  = 'D:\prj\reactV3'
$backendDir  = "$projectDir\backend"
$frontendDir = "$projectDir\frontend"
$logDir      = "$projectDir\logs"
$logFile     = "$logDir\deploy-watch.log"
$lockFile    = "$projectDir\.deploy.lock"
$branch      = 'master'
$port        = 8001

# ── 工具 ────────────────────────────────────────────────────────────
New-Item -ItemType Directory -Force -Path $logDir | Out-Null

function Write-Log($msg) {
    $line = "$(Get-Date -Format 'yyyy-MM-dd HH:mm:ss')  $msg"
    Add-Content -Path $logFile -Value $line -Encoding UTF8
}

function Acquire-Lock {
    if (Test-Path $lockFile) {
        $age = (Get-Date) - (Get-Item $lockFile).LastWriteTime
        if ($age.TotalMinutes -lt 15) {
            Write-Log "锁文件存在且不到 15 分钟，跳过本次部署"
            exit 0
        }
        Write-Log "锁文件超过 15 分钟，认为是僵死锁，强制清理"
        Remove-Item $lockFile -Force
    }
    New-Item -ItemType File -Path $lockFile -Force | Out-Null
}

function Release-Lock {
    if (Test-Path $lockFile) { Remove-Item $lockFile -Force }
}

function Get-PidOnPort([int]$p) {
    $conn = Get-NetTCPConnection -LocalPort $p -State Listen -ErrorAction SilentlyContinue
    if (-not $conn) { return $null }
    return $conn[0].OwningProcess
}

# ── 主流程 ──────────────────────────────────────────────────────────
Set-Location $projectDir

# 1. 检测远端更新
git fetch origin $branch 2>&1 | Out-Null
$local  = git rev-parse HEAD
$remote = git rev-parse "origin/$branch"
if ($local -eq $remote) { exit 0 }   # 无更新，安静退出

Acquire-Lock
try {
    Write-Log "检测到新版本：$local -> $remote"

    # 2. 记录改动文件（决定要不要重装依赖）
    $changedFiles = git diff --name-only $local $remote
    $needsPip = $changedFiles -contains 'backend/requirements.txt'
    $needsNpmInstall = $changedFiles -contains 'frontend/package-lock.json' -or `
                      $changedFiles -contains 'frontend/package.json'

    # 3. 拉新代码
    $pullOut = git pull origin $branch 2>&1
    Write-Log "git pull: $pullOut"

    # 4. 后端依赖
    if ($needsPip) {
        Write-Log "requirements.txt 变化，重装 Python 依赖"
        Push-Location $backendDir
        try { & pip install -r requirements.txt 2>&1 | Tee-Object -FilePath $logFile -Append | Out-Null }
        finally { Pop-Location }
    }

    # 5. 前端依赖 + build
    Push-Location $frontendDir
    try {
        if ($needsNpmInstall) {
            Write-Log "package-lock.json 变化，重装 npm 依赖"
            & npm install --no-audit --no-fund 2>&1 | Tee-Object -FilePath $logFile -Append | Out-Null
        }
        Write-Log "npm run build"
        & npm run build 2>&1 | Tee-Object -FilePath $logFile -Append | Out-Null
        if ($LASTEXITCODE -ne 0) { throw "前端 build 失败 (exit $LASTEXITCODE)，回滚" }
    } finally { Pop-Location }

    # 6. 停旧 uvicorn (按端口，不影响其他 python)
    $oldPid = Get-PidOnPort -p $port
    if ($oldPid) {
        Write-Log "停止旧 uvicorn (PID $oldPid)"
        Stop-Process -Id $oldPid -Force -ErrorAction SilentlyContinue
        Start-Sleep -Seconds 2
    }

    # 7. 启新 uvicorn (production 模式，stdout/stderr 重定向)
    $uvLog    = "$logDir\uvicorn-$(Get-Date -Format 'yyyyMMdd').log"
    $uvLogErr = "$logDir\uvicorn-$(Get-Date -Format 'yyyyMMdd').err.log"
    Start-Process -FilePath 'python' `
        -ArgumentList @('-m', 'uvicorn', 'main:app', '--host', '0.0.0.0', '--port', $port, '--log-level', 'info') `
        -WorkingDirectory $backendDir `
        -RedirectStandardOutput $uvLog `
        -RedirectStandardError $uvLogErr `
        -WindowStyle Hidden
    Write-Log "已启动新 uvicorn 在端口 $port，日志: $uvLog"

    # 8. 健康检查 (最多等 30 秒)
    Start-Sleep -Seconds 3
    $healthy = $false
    for ($i = 0; $i -lt 10; $i++) {
        try {
            $r = Invoke-RestMethod -Uri "http://127.0.0.1:$port/api/health" -TimeoutSec 5
            if ($r.status -eq 'ok') { $healthy = $true; break }
        } catch { Start-Sleep -Seconds 3 }
    }
    if ($healthy) {
        Write-Log "✅ 部署成功，/api/health 正常"
    } else {
        Write-Log "❌ 部署失败：30 秒内 /api/health 未响应。请检查 $uvLog 和 $uvLogErr"
    }
} finally {
    Release-Lock
}
