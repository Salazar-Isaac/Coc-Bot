@echo off
cd /d "%~dp0"
py -3.12 --version >nul 2>&1
if errorlevel 1 (
    echo Python 3.12 was not found. Run setup.bat or install Python 3.12.
    pause
    exit /b 1
)
py -3.12 main.py %*
if errorlevel 1 pause
