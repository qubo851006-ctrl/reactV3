<#
.SYNOPSIS
    Daily PostgreSQL backup for the reactv3 audit DB.

.DESCRIPTION
    Calls pg_dump to produce a compressed custom-format dump under
    D:/backup/pg/. Keeps the last 30 days by default; older files are
    pruned automatically.

    Wire to Task Scheduler (run daily at 02:00 ish):
        schtasks /create /tn "reactV3 PG backup" /tr "powershell -File D:\claude\reactV3\tools\backup_pg.ps1" /sc daily /st 02:00

    Restoring a dump:
        pg_restore -h 192.168.9.226 -U qubo -d reactv3 -c <dumpfile>
    (-c drops + recreates objects; omit if restoring to a fresh DB)

.PARAMETER PgDumpPath
    Full path to pg_dump.exe. If unset, assumes PATH.

.PARAMETER BackupRoot
    Where dumps land. Default D:/backup/pg.

.PARAMETER KeepDays
    Retain dumps newer than this many days. Default 30.
#>
[CmdletBinding()]
param(
    [string]$PgDumpPath = 'pg_dump',
    [string]$BackupRoot = 'D:/backup/pg',
    [int]$KeepDays = 30
)

$ErrorActionPreference = 'Stop'

# Pull connection info from backend/.env so this script stays in lockstep
# with the application's audit DB target.
$EnvFile = Join-Path (Split-Path -Parent $PSScriptRoot) 'backend\.env'
if (-not (Test-Path $EnvFile)) {
    throw "backend/.env not found at $EnvFile — run from project root or pass explicit creds."
}

function Get-EnvValue([string]$key) {
    $line = Select-String -Path $EnvFile -Pattern "^$key=(.*)$" -List | Select-Object -First 1
    if (-not $line) { return $null }
    return $line.Matches[0].Groups[1].Value.Trim()
}

$DbHost = Get-EnvValue 'DB_HOST'
$DbPort = Get-EnvValue 'DB_PORT'
$DbName = Get-EnvValue 'DB_NAME'
$DbUser = Get-EnvValue 'DB_USER'
$DbPwd  = Get-EnvValue 'DB_PASSWORD'

if (-not $DbHost -or -not $DbName -or -not $DbUser) {
    throw "DB_HOST / DB_NAME / DB_USER missing from $EnvFile"
}

New-Item -ItemType Directory -Force -Path $BackupRoot | Out-Null
$Stamp = Get-Date -Format 'yyyyMMdd-HHmmss'
$OutFile = Join-Path $BackupRoot "${DbName}_${Stamp}.dump"

Write-Host "[backup] $DbHost/$DbName → $OutFile"

# pg_dump reads PGPASSWORD from env to avoid interactive prompts.
$env:PGPASSWORD = $DbPwd
try {
    & $PgDumpPath `
        --host=$DbHost --port=$DbPort `
        --username=$DbUser `
        --format=custom --compress=6 `
        --file=$OutFile `
        $DbName
    if ($LASTEXITCODE -ne 0) {
        throw "pg_dump exited with code $LASTEXITCODE"
    }
    $size = (Get-Item $OutFile).Length
    Write-Host "[backup] OK — $([math]::Round($size / 1MB, 2)) MB"
}
finally {
    Remove-Item Env:PGPASSWORD -ErrorAction SilentlyContinue
}

# Prune old dumps
$Cutoff = (Get-Date).AddDays(-$KeepDays)
$pruned = Get-ChildItem $BackupRoot -Filter "${DbName}_*.dump" |
    Where-Object { $_.LastWriteTime -lt $Cutoff }
foreach ($f in $pruned) {
    Write-Host "[prune] removing $($f.Name) (older than $KeepDays days)"
    Remove-Item $f.FullName -Force
}
Write-Host "[backup] done."
