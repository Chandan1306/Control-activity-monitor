@echo off
:: ============================================================
:: Lab Monitor Agent — Task Scheduler Installer
:: Run this as Administrator on each student PC (once only)
:: ============================================================

echo.
echo  =============================================
echo   Lab Monitor Agent — Startup Installer
echo  =============================================
echo.

:: Check for admin rights
net session >nul 2>&1
if %errorLevel% neq 0 (
    echo  ERROR: Please right-click and "Run as administrator"
    pause
    exit /b 1
)

:: Check config.json exists
if not exist "%~dp0config.json" (
    echo  ERROR: config.json not found.
    echo  Create config.json with server_url and machine_token first.
    pause
    exit /b 1
)

:: Get Python path
for /f "tokens=*" %%i in ('python -c "import sys; print(sys.executable)"') do set PYTHON=%%i
set AGENT=%~dp0agent.py

echo  Python : %PYTHON%
echo  Agent  : %AGENT%
echo.

:: Remove existing task if present
schtasks /delete /tn "LabMonitorAgent" /f >nul 2>&1

:: Create scheduled task — runs at system startup, as SYSTEM, hidden
schtasks /create ^
  /tn "LabMonitorAgent" ^
  /tr "\"%PYTHON%\" \"%AGENT%\"" ^
  /sc onstart ^
  /ru SYSTEM ^
  /rl HIGHEST ^
  /f ^
  /delay 0000:30

if %errorLevel% neq 0 (
    echo  ERROR: Failed to create scheduled task.
    pause
    exit /b 1
)

:: Run it now immediately (no need to reboot)
echo  Starting agent now...
schtasks /run /tn "LabMonitorAgent"

echo.
echo  =============================================
echo   Done! Agent installed and running.
echo   It will start automatically on every boot.
echo  =============================================
echo.
pause
