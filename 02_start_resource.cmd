@echo off
setlocal
cd /d "%~dp0"
chcp 65001 >nul
set "PYTHONUTF8=1"
set "PYTHONUNBUFFERED=1"
set "NO_PROXY=127.0.0.1,localhost,::1"
if not defined GONGWEI_RESOURCE_PORT set "GONGWEI_RESOURCE_PORT=18011"
if not exist .venv\Scripts\python.exe goto missing
echo Starting the resource agent on 127.0.0.1:%GONGWEI_RESOURCE_PORT%.
echo Keep this window open. Do not change the host to 0.0.0.0.
echo This is a local-only simulation without platform certificates.
.venv\Scripts\python.exe -u -m uvicorn resource_agent:app --host 127.0.0.1 --port %GONGWEI_RESOURCE_PORT%
if errorlevel 1 goto failed
pause
exit /b 0
:failed
echo START FAILED. Check the error above; do not disable firewalls.
pause
exit /b 1
:missing
echo Run 01_prepare.cmd successfully first.
pause
exit /b 1
