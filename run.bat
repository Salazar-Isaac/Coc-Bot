@echo off
cd /d "%~dp0"
if exist "dist\Coc-Bot\Coc-Bot.exe" (
    start "" "dist\Coc-Bot\Coc-Bot.exe" %*
    exit /b
)
where pythonw >nul 2>&1 && (start "" pythonw main.py) || (start "" pyw -3 main.py)
