@echo off
setlocal
set SCRIPT_DIR=%~dp0
echo Setting up WeWIN Auto-Sync Scheduled Task...
powershell -ExecutionPolicy Bypass -File "%SCRIPT_DIR%setup_windows_sync.ps1"
pause
