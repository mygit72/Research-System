@echo off
rem Double-click this file to install (first run only) and start Research Intelligence.
rem It runs scripts\run-local.ps1, then opens http://localhost:5173 once the server is up.
setlocal
cd /d "%~dp0"

start "" /b cmd /c "timeout /t 6 >nul & start "" http://localhost:5173"

powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\run-local.ps1"

echo.
echo Server stopped. Press any key to close this window.
pause >nul
