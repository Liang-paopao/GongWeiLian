@echo off
setlocal
cd /d "%~dp0.."
call start_stage2.cmd
exit /b %errorlevel%
