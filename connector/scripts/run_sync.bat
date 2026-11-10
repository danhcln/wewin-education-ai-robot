@echo off
setlocal

:: Get root directory of project
set SCRIPT_DIR=%~dp0
cd /d "%SCRIPT_DIR%.."

:: Check for virtual environment in .venv or venv
if exist ".venv\Scripts\python.exe" (
    set PYTHON_EXEC=.venv\Scripts\python.exe
) else if exist "venv\Scripts\python.exe" (
    set PYTHON_EXEC=venv\Scripts\python.exe
) else (
    set PYTHON_EXEC=python
)

:: Create logs directory if it doesn't exist
if not exist "logs" mkdir "logs"

echo [%DATE% %TIME%] Starting WeWIN Auto-Sync via Task Scheduler... >> logs\sync_scheduled.log

%PYTHON_EXEC% run_sync.py --trigger task_scheduler --execute >> logs\sync_scheduled.log 2>&1

set EXIT_CODE=%ERRORLEVEL%
echo [%DATE% %TIME%] Sync finished with exit code %EXIT_CODE% >> logs\sync_scheduled.log

exit /b %EXIT_CODE%
