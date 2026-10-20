@echo off
setlocal
cd /d "%~dp0.."
call stop_stage2.cmd
exit /b %errorlevel%
