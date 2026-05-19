@echo off
REM ============================================================
REM  V3 后端停止器
REM  按端口 8001 找进程,不会误杀 V2 在 8000 的 uvicorn
REM ============================================================
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0stop.ps1"
pause
