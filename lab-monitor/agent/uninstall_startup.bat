@echo off
net session >nul 2>&1
if %errorLevel% neq 0 (
    echo Run as Administrator.
    pause
    exit /b 1
)
schtasks /end /tn "LabMonitorAgent" >nul 2>&1
schtasks /delete /tn "LabMonitorAgent" /f
echo Agent removed from startup.
pause
