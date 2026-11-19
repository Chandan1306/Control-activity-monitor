@echo off
:: ============================================================
:: Lab Monitor Agent — Service Installer
:: Run this as Administrator on each student PC (once only)
:: ============================================================

echo.
echo  =============================================
echo   Lab Monitor Agent — Service Installer
echo  =============================================
echo.

:: Check for admin rights
net session >nul 2>&1
if %errorLevel% neq 0 (
    echo  ERROR: Please right-click this file and choose
    echo         "Run as administrator"
    pause
    exit /b 1
)

:: Check config.json exists
if not exist "%~dp0config.json" (
    echo  ERROR: config.json not found in this folder.
    echo  Please create config.json with server_url and machine_token first.
    pause
    exit /b 1
)

:: Install pywin32 if needed
echo  Installing dependencies...
python -m pip install pywin32 pygetwindow pyrect requests --quiet

:: Run pywin32 post-install scripts (critical step)
echo  Running pywin32 post-install...
python -c "import win32serviceutil" >nul 2>&1
if %errorLevel% neq 0 (
    echo  Running pywin32 post-install setup...
    python Scripts\pywin32_postinstall.py -install >nul 2>&1
    for /f "tokens=*" %%i in ('python -c "import sys; print(sys.prefix)"') do set PYPREFIX=%%i
    python "%PYPREFIX%\Scripts\pywin32_postinstall.py" -install >nul 2>&1
)

:: Stop existing service if running
echo  Stopping existing service (if any)...
python "%~dp0agent_service.py" stop >nul 2>&1

:: Remove existing service
python "%~dp0agent_service.py" remove >nul 2>&1

:: Install and start service
echo  Installing service...
python "%~dp0agent_service.py" install

echo  Starting service...
python "%~dp0agent_service.py" start

echo.
echo  =============================================
echo   Done! Agent is now running as a service.
echo   It will start automatically on every boot.
echo  =============================================
echo.
pause
