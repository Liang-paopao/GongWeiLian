@echo off
setlocal
cd /d "%~dp0.."
if not exist .venv\Scripts\python.exe exit /b 1
.venv\Scripts\python.exe -m unittest discover -v
if errorlevel 1 exit /b %errorlevel%
.venv\Scripts\python.exe scripts\run_60_scenarios.py
if errorlevel 1 exit /b %errorlevel%
.venv\Scripts\python.exe run_stage2_tests.py
if errorlevel 1 exit /b %errorlevel%
.venv\Scripts\python.exe run_stage5_tests.py
exit /b %errorlevel%
