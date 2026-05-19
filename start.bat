@echo off
REM ============================================================
REM  V3 后端启动器 (端口 8001, production 模式)
REM  双击即可启动,日志在 logs/ 目录
REM  对应 stop.bat 用于停止
REM ============================================================
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0start.ps1"
pause
