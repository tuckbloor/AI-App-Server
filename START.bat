@echo off
setlocal EnableExtensions
cd /d "%~dp0"
title AI App Server
if not exist "%~dp0.venv\Scripts\python.exe" (
    echo AI App Server has not been installed in this folder.
    echo Run INSTALL.bat first, choosing this folder as the destination.
    pause
    exit /b 1
)
set "ACTION=start"
set "BROWSER_FLAG="
if /I "%~1"=="--background" set "BROWSER_FLAG=--no-browser"
if /I "%~1"=="--stop" set "ACTION=stop"
if /I "%~1"=="--status" set "ACTION=status"
if /I "%~1"=="--disable-autostart" set "ACTION=remove-startup"
"%~dp0.venv\Scripts\python.exe" -m ai_app_server.desktop_launcher %ACTION% --project "%CD%" %BROWSER_FLAG%
set "RESULT=%ERRORLEVEL%"
if not "%RESULT%"=="0" (
    echo The command failed. See the message above.
    if /I not "%~1"=="--background" pause
)
exit /b %RESULT%
