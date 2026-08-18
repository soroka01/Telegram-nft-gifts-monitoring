@echo off
setlocal EnableExtensions

cd /d "%~dp0"
chcp 65001 >nul
set "PYTHONUTF8=1"
set "PYTHONIOENCODING=utf-8"
title NFT Gift Monitor Login

echo.
echo NFT Gift Monitor Login
echo ======================
echo.

if not exist ".venv\Scripts\python.exe" (
    echo [ERROR] First run start.bat to create the virtual environment.
    pause
    exit /b 1
)

if not exist "config.json" (
    echo [ERROR] Fill config.json first.
    pause
    exit /b 1
)

"%~dp0.venv\Scripts\python.exe" "%~dp0login.py"
set "EXIT_CODE=%ERRORLEVEL%"

echo.
pause
exit /b %EXIT_CODE%
