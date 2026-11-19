"""
agent_builder.py — ZIP package generator for student PC deployment.

Generates a ready-to-deploy ZIP containing:
  - agent.exe  (pre-built) OR agent.py (fallback if exe not built yet)
  - config.json (auto-generated with token + server URL)
  - install.bat (creates scheduled task, no manual steps)
  - startup.vbs (silent launcher fallback)
  - README.txt

Usage:
  from agent_builder import build_agent_zip
  zip_bytes = build_agent_zip(machine_token, machine_name, server_url)
"""

import os
import io
import json
import shutil
import zipfile
import textwrap
import socket

# ── Paths ─────────────────────────────────────────────────────────────────────
SERVER_DIR = os.path.dirname(os.path.abspath(__file__))
AGENT_DIR  = os.path.join(SERVER_DIR, '..', 'agent')
BUILD_DIR  = os.path.join(SERVER_DIR, '..', 'build')
AGENT_EXE  = os.path.join(BUILD_DIR, 'agent.exe')
AGENT_PY   = os.path.join(AGENT_DIR, 'agent.py')


def get_server_ip():
    """Get the LAN IP of this machine (the server)."""
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(('8.8.8.8', 80))
        ip = s.getsockname()[0]
        s.close()
        return ip
    except Exception:
        return '127.0.0.1'


def _make_config(machine_token: str, machine_name: str, server_url: str) -> str:
    """Generate config.json content."""
    cfg = {
        "server_url":    server_url,
        "machine_token": machine_token,
        "machine_name":  machine_name
    }
    return json.dumps(cfg, indent=2)


def _make_install_bat(machine_name: str, use_exe: bool) -> str:
    return textwrap.dedent(f"""\
        @echo off
        :: Lab Monitor Agent Installer — {machine_name}
        :: Right-click → Run as Administrator

        echo.
        echo  Installing Lab Monitor Agent for {machine_name}...
        echo.

        net session >nul 2>&1
        if %errorLevel% neq 0 (
            echo  ERROR: Run as Administrator required.
            pause
            exit /b 1
        )

        set INSTALL_DIR=C:\\LabMonitorAgent
        if not exist "%INSTALL_DIR%" mkdir "%INSTALL_DIR%"

        :: Copy all files
        xcopy /E /I /Y "%~dp0*" "%INSTALL_DIR%\\" >nul
        echo  Files copied to %INSTALL_DIR%

        :: Remove old task
        schtasks /delete /tn "LabMonitorAgent" /f >nul 2>&1

        :: Get current user
        for /f "tokens=*" %%i in ('whoami') do set CURUSER=%%i

        :: Choose runner: prefer agent.exe, fall back to pythonw + agent.py
        if exist "%INSTALL_DIR%\\agent.exe" (
            set RUNNER="%INSTALL_DIR%\\agent.exe"
            echo  Using agent.exe
        ) else (
            for /f "tokens=*" %%p in ('where pythonw.exe 2^>nul') do set PYW=%%p
            if "%PYW%"=="" (
                for /f "tokens=*" %%p in ('where python.exe 2^>nul') do set PYW=%%p
            )
            if "%PYW%"=="" set PYW=C:\\Python313\\pythonw.exe
            set RUNNER="%PYW%" "%INSTALL_DIR%\\agent.py"
            echo  Using Python: %PYW%
        )

        :: Create scheduled task
        schtasks /create /tn "LabMonitorAgent" /tr %RUNNER% /sc onlogon /ru "%CURUSER%" /rl HIGHEST /f /delay 0000:10
        if %errorLevel% neq 0 (
            echo  Scheduled task failed. Using Startup folder fallback...
            copy /Y "%INSTALL_DIR%\\startup.vbs" "%APPDATA%\\Microsoft\\Windows\\Start Menu\\Programs\\Startup\\LabMonitorAgent.vbs" >nul
        )

        :: Start immediately
        echo  Starting agent...
        schtasks /run /tn "LabMonitorAgent" >nul 2>&1
        if %errorLevel% neq 0 (
            start "" /min %RUNNER%
        )

        timeout /t 5 /nobreak >nul

        echo.
        echo  ============================================================
        echo   Done! Agent installed for {machine_name}
        echo   Check C:\\LabMonitorAgent\\agent_log.txt if issues occur.
        echo  ============================================================
        echo.
        pause
    """)


def _make_startup_vbs(use_exe: bool) -> str:
    """Silent launcher fallback using WScript.Shell."""
    if use_exe:
        cmd = 'C:\\LabMonitorAgent\\agent.exe'
    else:
        cmd = 'pythonw C:\\LabMonitorAgent\\agent.py'

    return textwrap.dedent(f"""\
        ' Lab Monitor Agent — Silent Launcher
        ' Double-click or place in Startup folder to run silently
        Dim WshShell
        Set WshShell = CreateObject("WScript.Shell")
        WshShell.Run Chr(34) & "{cmd}" & Chr(34), 0, False
        Set WshShell = Nothing
    """)


def _make_readme(machine_name: str, server_url: str) -> str:
    """Generate README.txt with simple instructions."""
    return textwrap.dedent(f"""\
        ============================================================
         Lab Monitor Agent — {machine_name}
         Server: {server_url}
        ============================================================

        INSTALLATION INSTRUCTIONS
        -------------------------
        1. Extract this ZIP to your Desktop (or any folder)
        2. Right-click  install.bat
        3. Select "Run as administrator"
        4. Click Yes on the UAC prompt
        5. Done — the agent installs and starts automatically

        The agent will:
        - Run silently in the background (no visible window)
        - Start automatically every time Windows boots
        - Report activity to the Lab Monitor dashboard

        UNINSTALL
        ---------
        Open Command Prompt as Administrator and run:
          schtasks /delete /tn "LabMonitorAgent" /f

        SUPPORT
        -------
        Contact your lab instructor if you have issues.
        ============================================================
    """)


def build_agent_zip(
    machine_token: str,
    machine_name:  str,
    server_url:    str = None
) -> bytes:
    """
    Build a complete deployment ZIP for a student PC.

    Returns raw ZIP bytes ready to send as a file download.
    """
    if not server_url:
        server_url = f"http://{get_server_ip()}:5001"

    # Determine whether to use pre-built exe or .py fallback
    use_exe = os.path.exists(AGENT_EXE)

    # Build ZIP in memory
    zip_buffer = io.BytesIO()

    with zipfile.ZipFile(zip_buffer, 'w', zipfile.ZIP_DEFLATED) as zf:

        # Always include agent.py (works everywhere Python is installed)
        if os.path.exists(AGENT_PY):
            zf.write(AGENT_PY, 'agent.py')

        # Also include agent.exe if available (no Python needed)
        if use_exe:
            zf.write(AGENT_EXE, 'agent.exe')

        # config.json — auto-generated, no manual editing needed
        zf.writestr('config.json', _make_config(machine_token, machine_name, server_url))

        # install.bat — one-click installer
        zf.writestr('install.bat', _make_install_bat(machine_name, use_exe))

        # startup.vbs — silent launcher fallback
        zf.writestr('startup.vbs', _make_startup_vbs(use_exe))

        # README.txt
        zf.writestr('README.txt', _make_readme(machine_name, server_url))

    zip_buffer.seek(0)
    return zip_buffer.read()
