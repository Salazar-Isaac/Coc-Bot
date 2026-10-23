@echo off
setlocal
cd /d "%~dp0"
where pythonw >nul 2>&1
if not errorlevel 1 (
    start "" pythonw main.py %*
    exit /b
)
where pyw >nul 2>&1
if not errorlevel 1 (
    start "" pyw -3 main.py %*
    exit /b
)
set "PYW="
for /f "delims=" %%P in ('python -c "import os,sys; print(os.path.join(os.path.dirname(sys.executable), 'pythonw.exe'))" 2^>nul') do set "PYW=%%P"
if exist "%PYW%" (
    start "" "%PYW%" main.py %*
    exit /b
)
for /f "delims=" %%P in ('py -3 -c "import os,sys; print(os.path.join(os.path.dirname(sys.executable), 'pythonw.exe'))" 2^>nul') do set "PYW=%%P"
if exist "%PYW%" (
    start "" "%PYW%" main.py %*
    exit /b
)
if exist "dist\Coc-Bot\Coc-Bot.exe" (
    start "" "dist\Coc-Bot\Coc-Bot.exe" %*
    exit /b
)
echo A windowed Python interpreter was not found. Run setup.bat, or build the app with build.bat.
pause
exit /b 1
