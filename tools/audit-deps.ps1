# 依赖漏洞本地巡检（v3.6.19）—— 与 CI 的 security-audit job 同款检查，按需手动跑。
#
# 用法（在仓库根目录）：
#   pwsh tools/audit-deps.ps1          # 或 powershell tools/audit-deps.ps1
#
# 干什么：
#   - 后端：pip-audit 扫 backend/requirements.txt（生产依赖）对 PyPI/OSV 漏洞库
#   - 前端：npm audit 扫生产依赖，high/critical 才算失败
#
# 退出码：任一检查发现需关注的漏洞则非 0，便于挂到别的流程。
#
# 注意：本机 Windows 默认 GBK locale 会让 pip-audit 解析含制表符注释的
# requirements.txt 报 UnicodeDecodeError，这里用 PYTHONUTF8=1 强制 UTF-8。
# CI 跑在 ubuntu（UTF-8）无此问题。

$ErrorActionPreference = "Stop"
$repoRoot = Split-Path -Parent $PSScriptRoot
$failed = $false

Write-Host "===== 后端 pip-audit (backend/requirements.txt) =====" -ForegroundColor Cyan
Push-Location (Join-Path $repoRoot "backend")
try {
    $env:PYTHONUTF8 = "1"
    python -m pip show pip-audit *> $null
    if ($LASTEXITCODE -ne 0) {
        Write-Host "pip-audit 未安装，正在安装…" -ForegroundColor Yellow
        python -m pip install pip-audit --quiet
    }
    python -m pip_audit -r requirements.txt --progress-spinner=off
    if ($LASTEXITCODE -ne 0) { $failed = $true; Write-Host "⚠️ pip-audit 发现漏洞" -ForegroundColor Red }
    else { Write-Host "✅ 后端依赖无已知漏洞" -ForegroundColor Green }
}
finally { Pop-Location }

Write-Host "`n===== 前端 npm audit (生产依赖, high+) =====" -ForegroundColor Cyan
Push-Location (Join-Path $repoRoot "frontend")
try {
    npm audit --omit=dev --audit-level=high
    if ($LASTEXITCODE -ne 0) { $failed = $true; Write-Host "⚠️ npm audit 发现 high/critical 漏洞" -ForegroundColor Red }
    else { Write-Host "✅ 前端生产依赖无 high/critical 漏洞" -ForegroundColor Green }
}
finally { Pop-Location }

if ($failed) {
    Write-Host "`n❌ 依赖巡检发现需关注的漏洞，请处理或评估后再发布。" -ForegroundColor Red
    exit 1
}
Write-Host "`n✅ 依赖巡检通过。" -ForegroundColor Green
