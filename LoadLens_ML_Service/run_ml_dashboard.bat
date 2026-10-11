@echo off
title LoadLens AIoT & ML Cloud Web Service
cd /d "%~dp0"
echo ================================================================
echo    Starting LoadLens AIoT & Machine Learning Dashboard
echo ================================================================
echo.
echo  * Training / Checking Random Forest ML Model...
python train_model.py
echo.
echo  * Starting Web Dashboard & 5-Second Telemetry Logger...
echo  * Open your browser to: http://127.0.0.1:8000
echo.
python -m uvicorn app:app --host 127.0.0.1 --port 8000
pause
