@echo off
setlocal
cd /d "%~dp0"
if not exist ".venv\Scripts\python.exe" (
 echo Please run START HERE.bat to install the application first.
 pause
 exit /b 1
)
set "APPLICATION=app\app.py"
if exist "examples\app.py" set "APPLICATION=examples\app.py"
echo AI App Server - Production security checklist
echo Local Development does NOT require HTTPS.
echo Production requires every item below to pass.
echo.
".venv\Scripts\python.exe" -m ai_app_server.cli doctor "%APPLICATION%" --data-dir "data"
echo.
pause
