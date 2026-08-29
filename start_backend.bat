@echo off
cd /d %~dp0
if not exist .venv\Scripts\python.exe (
  echo [ERROR] .venv not found. Run: py -m venv .venv
  pause
  exit /b 1
)
rem Canonical package entry point; root web_api.py remains compatible for older deployments.
.venv\Scripts\python.exe -m uvicorn backend.web_api:app --reload --host 127.0.0.1 --port 8000
pause
