@echo off
setlocal
cd /d "%~dp0"
title Coc-Bot setup
echo ============================================
echo   Coc-Bot setup
echo ============================================
echo.

rem --- use the required Python version, regardless of the PATH default ---
set "PY=py -3.12"
%PY% --version >nul 2>&1
if errorlevel 1 (
    echo Python 3.12 was not found.
    echo Install Python 3.12 from https://www.python.org/downloads/
    echo and tick "Add python.exe to PATH" during the install. Then run setup.bat again.
    echo.
    pause
    exit /b 1
)
for /f "delims=" %%v in ('%PY% --version') do echo Using %%v
echo.

echo Installing / updating the packages (this can take a few minutes the first time)...
%PY% -m pip install --upgrade pip --disable-pip-version-check -q
%PY% -m pip install -r requirements.txt --disable-pip-version-check
if errorlevel 1 (
    echo.
    echo Installing the packages failed. Check the messages above and your internet connection.
    pause
    exit /b 1
)
echo.

choice /c YN /n /m "Create a Coc-Bot shortcut on the desktop? [Y/N] "
if errorlevel 2 (
    %PY% tools\check_setup.py
) else (
    %PY% tools\check_setup.py --shortcut
)
echo.
pause
