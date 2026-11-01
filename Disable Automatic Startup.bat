@echo off
cd /d "%~dp0"
if not exist ".venv\Scripts\python.exe" exit /b 1
".venv\Scripts\python.exe" -m ai_app_server.desktop_launcher remove-startup
if errorlevel 1 pause
