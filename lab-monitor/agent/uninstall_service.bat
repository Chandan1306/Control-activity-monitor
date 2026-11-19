@echo off
echo  Stopping and removing Lab Monitor Agent service...
net session >nul 2>&1
if %errorLevel% neq 0 (
    echo  ERROR: Run as Administrator.
    pause
    exit /b 1
)
python "%~dp0agent_service.py" stop
python "%~dp0agent_service.py" remove
echo  Done. Agent service removed.
pause
