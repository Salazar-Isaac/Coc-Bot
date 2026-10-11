@echo off
cd /d "%~dp0"
where pythonw >nul 2>&1 && (start "" pythonw main.py) || (start "" pyw -3 main.py)
