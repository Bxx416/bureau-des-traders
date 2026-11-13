@echo off
title Installation du Bureau des Traders
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0installer\installer.ps1"
if errorlevel 1 pause
