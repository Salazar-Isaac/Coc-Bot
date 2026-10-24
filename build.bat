@echo off
setlocal
cd /d "%~dp0"
title Coc-Bot executable build
echo ============================================
echo   Building Coc-Bot for Windows
echo ============================================
echo.

set "PY="
py -3.12 --version >nul 2>&1 && set "PY=py -3.12"
if not defined PY (
    echo Python 3.12 was not found. Install Python 3.12 and try again.
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
