@echo off
title LoadLens Telemetry CSV Logger
cd /d "%~dp0"
echo ======================================================
echo    Starting LoadLens Automatic Telemetry CSV Logger
echo ======================================================
echo.
.\venv\Scripts\python.exe logger.py
pause
