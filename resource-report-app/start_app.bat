@echo off
title Team Resource Utilization Reporting System
echo ======================================================================
echo Starting Team Resource Utilization Reporting System...
echo ======================================================================
echo.
echo Initializing local environment and SQLite database...
cd /d "%~dp0"

echo Opening browser at http://localhost:8000 ...
timeout /t 2 /nobreak >nul
start "" http://localhost:8000

echo Starting backend application server...
python app.py
if %ERRORLEVEL% NEQ 0 (
    echo.
    echo [ERROR] Application encountered an issue during startup.
    pause
)
