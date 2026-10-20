@echo off
setlocal
cd /d "%~dp0"
chcp 65001 >nul
set "PYTHONUTF8=1"
set "NO_PROXY=127.0.0.1,localhost,::1"
if not defined GONGWEI_RESOURCE_PORT set "GONGWEI_RESOURCE_PORT=18011"
if not exist .venv\Scripts\python.exe goto missing
echo Running the leader against 127.0.0.1:%GONGWEI_RESOURCE_PORT%.
.venv\Scripts\python.exe -u leader.py
if errorlevel 1 goto failed
pause
exit /b 0
:missing
echo Run 01_prepare.cmd successfully first.
pause
exit /b 1
:failed
echo The local check did not pass. Keep the error text for troubleshooting.
echo Do not report this as a passed test or as a platform verification.
pause
exit /b 1
