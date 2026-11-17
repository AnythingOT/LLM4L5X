@echo off
REM LLM4L5X one-click start for Windows.
REM First run: creates .venv and installs requirements. Later runs: just starts the GUI.
cd /d "%~dp0"

where python >nul 2>nul
if errorlevel 1 (
    echo Python was not found. Install Python 3.10+ from python.org and tick "Add python.exe to PATH".
    pause
    exit /b 1
)

if not exist ".venv\Scripts\python.exe" (
    echo Creating virtual environment...
    python -m venv .venv || goto :fail
    ".venv\Scripts\python.exe" -m pip install --upgrade pip || goto :fail
    ".venv\Scripts\python.exe" -m pip install -r requirements.txt || goto :fail
)

echo Starting LLM4L5X at http://127.0.0.1:5000  (close this window to stop)
start "" http://127.0.0.1:5000
".venv\Scripts\python.exe" app.py
exit /b 0

:fail
echo Setup failed. See the messages above.
pause
exit /b 1
