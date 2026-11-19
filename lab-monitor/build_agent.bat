@echo off
:: ============================================================
:: Build agent.exe using PyInstaller
:: Run this ONCE on the server machine to compile the agent.
:: Output: lab-monitor/build/agent.exe
:: ============================================================

echo.
echo  Building Lab Monitor Agent EXE...
echo.

:: Install PyInstaller if not present
python -m pip install pyinstaller --quiet

:: Create build output directory
if not exist "%~dp0build" mkdir "%~dp0build"

:: Build the EXE
:: --onefile     = single standalone EXE
:: --noconsole   = no terminal window (silent)
:: --name        = output filename
:: --distpath    = output directory

pyinstaller ^
  --onefile ^
  --noconsole ^
  --name agent ^
  --distpath "%~dp0build" ^
  --workpath "%~dp0build\_work" ^
  --specpath "%~dp0build\_spec" ^
  --hidden-import pygetwindow ^
  --hidden-import pyrect ^
  --hidden-import requests ^
  --hidden-import json ^
  --hidden-import socket ^
  "%~dp0agent\agent.py"

if %errorLevel% neq 0 (
    echo.
    echo  ERROR: Build failed. Check output above.
    pause
    exit /b 1
)

:: Clean up build artifacts (keep only agent.exe)
if exist "%~dp0build\_work" rmdir /s /q "%~dp0build\_work"
if exist "%~dp0build\_spec" rmdir /s /q "%~dp0build\_spec"

echo.
echo  ============================================================
echo   Build successful!
echo   Output: %~dp0build\agent.exe
echo   Now use the dashboard to generate agent ZIPs.
echo  ============================================================
echo.
pause
