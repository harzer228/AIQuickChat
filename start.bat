@echo off
setlocal
cd /d "%~dp0"

if not exist ".venv\Scripts\python.exe" (
    echo [AI Quick Chat] Virtual environment not found. Creating...
    python -m venv .venv
    if errorlevel 1 (
        echo [AI Quick Chat] Failed to create venv. Install Python 3.11+ first.
        pause
        exit /b 1
    )
    .venv\Scripts\python.exe -m pip install --upgrade pip
    .venv\Scripts\python.exe -m pip install -r requirements.txt
    if errorlevel 1 (
        echo [AI Quick Chat] Failed to install dependencies.
        pause
        exit /b 1
    )
    echo [AI Quick Chat] Dependencies installed.
)

start "" /B ".venv\Scripts\pythonw.exe" main.py
echo [AI Quick Chat] Starting in background. Show/hide with Ctrl+Space, tray icon to exit.
exit /b 0
