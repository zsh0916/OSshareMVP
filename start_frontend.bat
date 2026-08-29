@echo off
cd /d %~dp0frontend
rem Dependencies and dist are local/generated files and are intentionally ignored by Git.
if not exist node_modules (
  echo Installing frontend dependencies...
  call npm install
)
call npm run dev
pause
