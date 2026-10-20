@echo off
setlocal
cd /d "%~dp0"
chcp 65001 >nul
set "PYTHONUTF8=1"
echo Gongwei step 1 - install the official SDK and check local files.
echo This downloads Python and dependencies. It does not log into Wutong.
set "UV_EXE="
where uv.exe >nul 2>nul
if not errorlevel 1 set "UV_EXE=uv.exe"
if not defined UV_EXE if defined APPDATA for /d %%D in ("%APPDATA%\Python\Python*") do if not defined UV_EXE if exist "%%~fD\Scripts\uv.exe" set "UV_EXE=%%~fD\Scripts\uv.exe"
if not defined UV_EXE goto missing_uv
where git >nul 2>nul
if errorlevel 1 goto missing_git
if not exist logs mkdir logs
echo Downloading dependencies. Progress is recorded in logs\setup.log.
set "PYTHON_RUNTIME=%~dp0.python-runtime"
set "PYTHON_EXE=%PYTHON_RUNTIME%\cpython-3.14.8-windows-x86_64-none\python.exe"
if not exist "%PYTHON_EXE%" (
  echo Installing the project-local Python 3.14 runtime. >> logs\setup.log
  "%UV_EXE%" python install 3.14.8 --install-dir "%PYTHON_RUNTIME%" --no-bin >> logs\setup.log 2>&1
  if errorlevel 1 goto failed
)
echo Using Python runtime: %PYTHON_EXE% >> logs\setup.log
if not exist "%PYTHON_EXE%" goto failed
"%UV_EXE%" sync --python "%PYTHON_EXE%" --no-dev >> logs\setup.log 2>&1
if errorlevel 1 goto failed
.venv\Scripts\python.exe -c "from acps_sdk.aip import AipRpcClient; from acps_sdk.aip.aip_rpc_server import add_aip_rpc_router; import resource_agent; print('SDK IMPORT OK')" >> logs\setup.log 2>&1
if errorlevel 1 goto failed
.venv\Scripts\python.exe -m unittest -v test_business >> logs\setup.log 2>&1
if errorlevel 1 goto failed
type logs\setup.log
echo.
echo SETUP OK. Next: double-click 02_start_resource.cmd.
echo No platform verification has been performed.
pause
exit /b 0
:missing_uv
echo uv was not found. Install uv first, then close and reopen this window.
pause
exit /b 1
:missing_git
echo Git was not found. Install Git for Windows, then reopen this window.
pause
exit /b 1
:failed
echo SETUP FAILED. Do not continue to step 02.
echo Check logs\setup.log. No success result has been generated.
type logs\setup.log
pause
exit /b 1
