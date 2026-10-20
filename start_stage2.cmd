@echo off
setlocal
cd /d "%~dp0"
chcp 65001 >nul
set "PYTHONUTF8=1"
set "PYTHONUNBUFFERED=1"
set "NO_PROXY=127.0.0.1,localhost,::1"
if not defined GONGWEI_STAGE2_RESOURCE_PORT set "GONGWEI_STAGE2_RESOURCE_PORT=18012"
if not defined GONGWEI_STAGE2_WORKORDER_PORT set "GONGWEI_STAGE2_WORKORDER_PORT=18013"
if not defined GONGWEI_STAGE2_AUDIO_PORT set "GONGWEI_STAGE2_AUDIO_PORT=18014"
if not defined GONGWEI_STAGE2_LEADER_PORT set "GONGWEI_STAGE2_LEADER_PORT=18010"
if not exist .venv\Scripts\python.exe goto missing
"%~dp0.venv\Scripts\python.exe" -u "%~dp0scripts\local_services.py" start
exit /b %errorlevel%
:missing
echo Run 01_prepare.cmd successfully first.
exit /b 1
