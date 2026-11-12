@echo off
title Bureau des Traders
cd /d "%~dp0"
"app\.venv\Scripts\python.exe" app\server.py
if errorlevel 1 pause
