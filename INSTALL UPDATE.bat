@echo off
setlocal
cd /d "%~dp0"
title AI App Server - v0.9.1 Safe Overlay Update
cls
echo ================================================
echo    AI APP SERVER v0.9.1 - SAFE OVERLAY UPDATE
echo ================================================
echo.
echo Your app, SQLite data, passwords and port settings remain in place.
echo Upgrade, backup, restart and error recovery are automatic.
echo.
set "INSTALL=%~dp0..\ai-app-server"
if not exist "%INSTALL%\engine\ai_app_server\version.py" (
 echo ERROR: Existing installation not found at:
 echo %INSTALL%
 echo Extract the OVERLAY folder next to E:\ai-app-server.
 goto :bad
)
if not exist "%INSTALL%\.venv\Scripts\python.exe" (
 echo ERROR: Existing Python environment not found. No files changed.
 goto :bad
)
"%INSTALL%\.venv\Scripts\python.exe" "%~dp0installer.py" --target "%INSTALL%"
if errorlevel 1 goto :bad
echo.
echo Installation complete.
pause
exit /b 0
:bad
echo.
echo Nothing needs to be deleted. See the error above.
pause
exit /b 1
