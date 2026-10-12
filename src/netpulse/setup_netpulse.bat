@echo off
setlocal
cd /d "%~dp0"
set "NETPULSE_PYTHON=.venv\Scripts\python.exe"
if not exist "%NETPULSE_PYTHON%" set "NETPULSE_PYTHON=.venv313\Scripts\python.exe"
if not exist "%NETPULSE_PYTHON%" (
  py -3 -m venv .venv
  if errorlevel 1 exit /b 1
  set "NETPULSE_PYTHON=.venv\Scripts\python.exe"
)
"%NETPULSE_PYTHON%" -m pip install -r requirements.txt
if errorlevel 1 exit /b 1
if not exist targets.json copy targets.example.json targets.json >nul
"%NETPULSE_PYTHON%" -m pytest -q
if errorlevel 1 exit /b 1
echo Setup complete. Review targets.json, then run start_netpulse.bat.
endlocal
