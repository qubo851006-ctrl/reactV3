@echo off
pushd D:\claude\reactV2\backend
uvicorn main:app --reload --port 8000
popd
pause
