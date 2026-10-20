@echo off
setlocal
cd /d "%~dp0.."
if /I not "%GONGWEI_RESET_DEMO_CONFIRM%"=="RESET-DEMO" (
  echo Set GONGWEI_RESET_DEMO_CONFIRM=RESET-DEMO before resetting simulated data.
  exit /b 2
)
.venv\Scripts\python.exe -c "from stage2_domain import reset_database; reset_database()"
exit /b %errorlevel%
