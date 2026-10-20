@echo off
setlocal
cd /d "%~dp0"
chcp 65001 >nul
set "PYTHONUTF8=1"
if not exist .venv\Scripts\python.exe (
  echo Missing project Python runtime. No processes were stopped.
  exit /b 1
)
"%~dp0.venv\Scripts\python.exe" -u "%~dp0scripts\local_services.py" stop
exit /b %errorlevel%
