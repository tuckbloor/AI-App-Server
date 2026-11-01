@echo off
cd /d "%~dp0"
if not exist ".venv\Scripts\python.exe" (
  call "%~dp0START HERE.bat"
  exit /b %errorlevel%
)
".venv\Scripts\python.exe" -m ai_app_server.desktop_launcher start
if errorlevel 1 pause
