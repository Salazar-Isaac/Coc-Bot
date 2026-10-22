@echo off
setlocal
cd /d "%~dp0"
title Coc-Bot executable build
echo ============================================
echo   Building Coc-Bot for Windows
echo ============================================
echo.

set "PY="
python --version >nul 2>&1 && set "PY=python"
if not defined PY (
    py -3 --version >nul 2>&1 && set "PY=py -3"
)
if not defined PY (
    echo Python was not found. Install Python 3.10 or newer and try again.
    pause
    exit /b 1
)

echo Installing build tools if needed...
%PY% -m pip install -r requirements-build.txt --disable-pip-version-check
if errorlevel 1 (
    echo.
    echo Installing PyInstaller failed.
    pause
    exit /b 1
)

echo.
%PY% tools\build_exe.py
if errorlevel 1 (
    echo.
    echo The executable build failed. Check the messages above.
    pause
    exit /b 1
)

echo.
echo Ready. Run dist\Coc-Bot\Coc-Bot.exe or run run.bat.
pause
