@echo off
setlocal EnableDelayedExpansion
REM start.bat – Windows launcher (double-click to run)

cd /d "%~dp0"

echo ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
echo    AI Video Agent
echo ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

REM ── Find Python ────────────────────────────────────────────────────────────
set PYTHON=
for %%P in (python python3) do (
    if "!PYTHON!"=="" (
        where %%P >nul 2>&1
        if not errorlevel 1 set PYTHON=%%P
    )
)

if "%PYTHON%"=="" (
    echo ERROR: Python not found.
    echo Download from https://www.python.org/downloads/
    pause
    exit /b 1
)

echo Python: %PYTHON%

REM ── Install Python dependencies ────────────────────────────────────────────
echo Checking Python dependencies...
%PYTHON% -m pip install -q -r requirements.txt

REM ── Launch Adobe Premiere Pro (if not already running) ─────────────────────
tasklist /FI "IMAGENAME eq Adobe Premiere Pro.exe" 2>nul | find /I "Adobe Premiere Pro.exe" >nul
if errorlevel 1 (
    REM Not running – try to find and launch it
    set PREMIERE_EXE=
    for /d %%D in ("C:\Program Files\Adobe\Adobe Premiere Pro*") do (
        if exist "%%D\Adobe Premiere Pro.exe" (
            set PREMIERE_EXE=%%D\Adobe Premiere Pro.exe
        )
    )
    if defined PREMIERE_EXE (
        echo Launching Adobe Premiere Pro...
        start "" "!PREMIERE_EXE!"
    ) else (
        echo Adobe Premiere Pro not found - skipping ^(Premiere features won't be available^)
    )
) else (
    echo Adobe Premiere Pro already running
)

REM ── Open browser after short delay (runs in background) ───────────────────
start /B cmd /c "timeout /t 4 /nobreak >nul && start http://localhost:8000"

REM ── Kill any leftover server on port 8000 ─────────────────────────────────
for /f "tokens=5" %%P in ('netstat -ano ^| findstr ":8000 " ^| findstr "LISTENING"') do (
    echo Killing old server process %%P...
    taskkill /PID %%P /F >nul 2>&1
)

REM ── Start server in foreground (closing this window stops the server) ──────
echo Starting server on http://localhost:8000 ...
echo Close this window to stop the server.
echo.
%PYTHON% server.py
echo.
echo Server stopped. Press any key to close...
pause
