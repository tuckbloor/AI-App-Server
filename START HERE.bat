@echo off
setlocal
cd /d "%~dp0"
title AI App Server - One Click Setup
echo.
echo  ==========================================
echo             AI APP SERVER
 echo        ONE CLICK INSTALL AND START
 echo  ==========================================
echo.
echo  Checking Python and preparing the application...
echo.
if not exist ".venv\Scripts\python.exe" (
  where py >nul 2>nul
  if not errorlevel 1 (
    py -3 -m venv .venv
  ) else (
    where python >nul 2>nul
    if errorlevel 1 (
      echo ERROR: Python was not found. Install Python 3.11 or newer.
      goto :failed
    )
    python -m venv .venv
  )
)
if not exist ".venv\Scripts\python.exe" (
  echo ERROR: Could not create Python environment.
  goto :failed
)
echo  Installing or updating required Python packages (automatic)...
".venv\Scripts\python.exe" tools\bootstrap.py
if errorlevel 1 goto :failed
".venv\Scripts\python.exe" -m pip install --disable-pip-version-check -e engine
if errorlevel 1 (
  echo ERROR: Could not install required Python packages.
  goto :failed
)
echo.
echo  Starting the local server and checking its connection...
".venv\Scripts\python.exe" -m ai_app_server.desktop_launcher install
if errorlevel 1 goto :failed
echo.
echo  SUCCESS: The application is running in the background.
echo  It will start automatically after you sign in to Windows.
echo  You may close this window. Your SQLite data stays in the data folder.
echo.
pause
exit /b 0
:failed
echo.
echo  SETUP DID NOT FINISH. Nothing has been deleted.
echo  Copy the error above if you need help.
echo.
pause
exit /b 1
