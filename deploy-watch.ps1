# ── 自动部署脚本 deploy-watch.ps1 ────────────────────────────────
# 每次由任务计划程序调用，检测到新 commit 时自动 pull + 重启后端

$projectDir = "D:\prj\react-master\react-master"
$backendDir  = "$projectDir\backend"
$logFile     = "D:\prj\deploy-watch.log"
$branch      = "master"

function Write-Log($msg) {
    $line = "$(Get-Date -Format 'yyyy-MM-dd HH:mm:ss')  $msg"
    Add-Content -Path $logFile -Value $line
}

Set-Location $projectDir

# 拉取远程信息（不改本地代码）
git fetch origin $branch 2>&1 | Out-Null

$local  = git rev-parse HEAD
$remote = git rev-parse "origin/$branch"

if ($local -eq $remote) {
    exit 0   # 无更新，安静退出
}

Write-Log "检测到新版本：$local -> $remote，开始部署"

# 拉取新代码
$pullOut = git pull origin $branch 2>&1
Write-Log "git pull: $pullOut"

# 停止旧 uvicorn 进程
Get-Process python -ErrorAction SilentlyContinue | Stop-Process -Force
Start-Sleep -Seconds 2

# 启动新 uvicorn
Start-Process python `
    -ArgumentList "-m uvicorn main:app --host 0.0.0.0 --port 8000" `
    -WorkingDirectory $backendDir `
    -NoNewWindow

Write-Log "部署完成，uvicorn 已重启"
