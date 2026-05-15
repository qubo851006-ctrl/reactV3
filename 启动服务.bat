@echo off
cd /d "%~dp0backend"
py -3.11 -m pip install -r requirements.txt
py -3.11 -m uvicorn main:app --host 0.0.0.0 --port 8000
pause
