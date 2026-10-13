@echo off
setlocal
cd /d "%~dp0"
set "NETPULSE_PYTHON=.venv\Scripts\python.exe"
if not exist "%NETPULSE_PYTHON%" set "NETPULSE_PYTHON=.venv313\Scripts\python.exe"
if not exist "%NETPULSE_PYTHON%" exit /b 1
"%NETPULSE_PYTHON%" scripts\launcher.py --stop
endlocal
