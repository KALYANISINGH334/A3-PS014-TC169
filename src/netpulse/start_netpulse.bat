@echo off
setlocal
cd /d "%~dp0"
set "NETPULSE_PYTHON=.venv\Scripts\python.exe"
if not exist "%NETPULSE_PYTHON%" set "NETPULSE_PYTHON=.venv313\Scripts\python.exe"
if not exist "%NETPULSE_PYTHON%" (
  echo No existing virtual environment found. Run setup_netpulse.bat once.
  pause
  exit /b 1
)
"%NETPULSE_PYTHON%" scripts\launcher.py
if errorlevel 1 pause
endlocal
