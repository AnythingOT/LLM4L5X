@echo off
REM LLM4L5X one-click start for Windows.
REM The packages live outside this folder, in %LOCALAPPDATA%\LLM4L5X\venv (or %LLM4L5X_VENV% if set),
REM so a new download of the repo starts at once: they are installed once, and again only when
REM requirements.txt changes. A .venv folder inside an older download is no longer used: delete it.
setlocal
cd /d "%~dp0"

where python >nul 2>nul
if errorlevel 1 (
    echo Python was not found. Install Python 3.10+ from python.org and tick "Add python.exe to PATH".
    pause
    exit /b 1
)

if defined LLM4L5X_VENV (set "VENV=%LLM4L5X_VENV%") else (set "VENV=%LOCALAPPDATA%\LLM4L5X\venv")
set "PY=%VENV%\Scripts\python.exe"

REM A venv made by a Python that is gone, upgraded or removed, does not run: make it again.
if not exist "%PY%" goto :create
"%PY%" -c "import sys" >nul 2>nul
if not errorlevel 1 goto :packages
echo The package folder no longer works with this Python: making it again.
rmdir /s /q "%VENV%"

:create
echo First start: installing the packages once. This takes a few minutes.
python -m venv "%VENV%"
if errorlevel 1 goto :fail

:packages
REM Install when requirements.txt is new or changed since the last install; fc fails if the copy is missing.
fc /b requirements.txt "%VENV%\requirements.txt" >nul 2>nul
if not errorlevel 1 goto :run
echo Installing packages: requirements.txt is new or changed.
"%PY%" -m pip install --upgrade pip >nul
"%PY%" -m pip install -r requirements.txt
if errorlevel 1 goto :fail
copy /y requirements.txt "%VENV%\requirements.txt" >nul

:run
echo Starting LLM4L5X at http://127.0.0.1:5000  - close this window to stop
echo Keep the model server on this PC: never start llama-server or Ollama with --host 0.0.0.0
start "" http://127.0.0.1:5000
"%PY%" app.py
exit /b 0

:fail
echo Setup failed. See the messages above.
pause
exit /b 1
