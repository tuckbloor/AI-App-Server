@echo off
cd /d "%~dp0"
if not exist ".venv\Scripts\python.exe" (
 echo AI App Server has not been installed yet.
 pause
 exit /b 1
)
".venv\Scripts\python.exe" -m ai_app_server.desktop_launcher stop
if errorlevel 1 pause
