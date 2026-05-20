@echo off
chcp 65001 >nul
tasklist /FI "IMAGENAME eq caddy.exe" 2>nul | findstr /I caddy.exe >nul
if errorlevel 1 (
    echo [stop-https] Caddy is not running
) else (
    taskkill /F /IM caddy.exe
    echo [stop-https] Caddy stopped
)
