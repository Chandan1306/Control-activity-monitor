@echo off
:: Simple agent runner — no EXE needed
:: Place this in the same folder as agent.py and config.json

cd /d "%~dp0"
pythonw agent.py
