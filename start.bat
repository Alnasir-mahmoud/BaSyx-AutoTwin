@echo off
REM ════════════════════════════════════════════════════════════════════
REM   AAS-Studio · One-Click-Bootstrap
REM ════════════════════════════════════════════════════════════════════
REM   Detects the host LAN IP, scans free ports for every service,
REM   writes .env + GUI/connection.json, then runs docker compose up.
REM
REM   Usage:   start.bat              ← normal start
REM            start.bat clean        ← tear down + rebuild
REM            start.bat status       ← only show URLs, no restart
REM ════════════════════════════════════════════════════════════════════

setlocal
cd /d "%~dp0"

powershell.exe -NoLogo -NoProfile -ExecutionPolicy Bypass -File "%~dp0start.ps1" %*
set "EXITCODE=%ERRORLEVEL%"

if %EXITCODE% NEQ 0 (
    echo.
    echo [ERROR] start.ps1 failed with exit code %EXITCODE%.
    pause
)

endlocal & exit /b %EXITCODE%
