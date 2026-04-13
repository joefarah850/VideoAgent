@echo off
setlocal

echo ================================================
echo   AI Video Agent - Premiere Pro Plugin Installer
echo ================================================
echo.

set PLUGIN_SRC=%~dp0premiere-plugin
set CEP_DIR=%APPDATA%\Adobe\CEP\extensions
set DEST=%CEP_DIR%\com.videoagent.plugin

echo Source : %PLUGIN_SRC%
echo Dest   : %DEST%
echo.

REM ── Check source exists ──────────────────────────────────────────────────────
if not exist "%PLUGIN_SRC%\CSXS\manifest.xml" (
    echo ERROR: premiere-plugin folder not found.
    echo Make sure you run this from the VideoAgent folder.
    goto :end
)

REM ── Create CEP extensions folder if missing ──────────────────────────────────
if not exist "%CEP_DIR%" mkdir "%CEP_DIR%"

REM ── Remove old installation ───────────────────────────────────────────────────
if exist "%DEST%" (
    echo Removing old installation...
    rmdir /s /q "%DEST%"
)

REM ── Copy plugin files ─────────────────────────────────────────────────────────
echo Copying plugin files...
xcopy /e /i /q "%PLUGIN_SRC%" "%DEST%"
if errorlevel 1 (
    echo ERROR: Could not copy files.
    goto :end
)
echo Done. Plugin installed to:
echo   %DEST%
echo.

REM ── Enable unsigned CEP extensions in registry ────────────────────────────────
echo Enabling unsigned CEP extensions...
for %%V in (9 10 11 12) do (
    reg add "HKCU\Software\Adobe\CSXS.%%V" /v PlayerDebugMode /t REG_SZ /d 1 /f >nul 2>&1
)
echo   Registry updated for CSXS 9-12.
echo.

echo ================================================
echo   Installation complete!
echo.
echo   Next steps:
echo   1. Close and reopen Adobe Premiere Pro
echo   2. Go to Window -^> Extensions -^> AI Video Agent
echo   3. Run start.bat
echo   4. The panel dot turns green when connected
echo ================================================

:end
echo.
pause
