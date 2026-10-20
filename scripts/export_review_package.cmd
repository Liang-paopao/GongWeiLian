@echo off
setlocal
cd /d "%~dp0.."
.venv\Scripts\python.exe scripts\make_final_project_audit.py
exit /b %errorlevel%
