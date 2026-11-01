@echo off
setlocal
cd /d "%~dp0"
set "AI_APP_SERVER_DATA_DIR=%~dp0data"
if not exist ".venv\Scripts\python.exe" (
  echo Creating Python virtual environment...
  where py >nul 2>nul
  if not errorlevel 1 (
    py -m venv .venv
  ) else (
    python -m venv .venv
  )
  if errorlevel 1 (echo Failed to create Python environment & pause & exit /b 1)
)
echo Installing AI App Server...
".venv\Scripts\python.exe" tools\bootstrap.py
if errorlevel 1 (echo Application preparation failed & pause & exit /b 1)
".venv\Scripts\python.exe" -m pip install -e engine
if errorlevel 1 (echo Package installation failed & pause & exit /b 1)
echo.
echo The app URL and admin address will be shown below based on your selected port.
echo First-run admin: admin / password (change immediately, do not use on a public network)
echo.
if exist "examples\app.py" (
  set "APP_SCRIPT=examples\app.py"
) else (
  set "APP_SCRIPT=app\app.py"
)
".venv\Scripts\python.exe" -m ai_app_server.cli run "%APP_SCRIPT%" --data-dir "%AI_APP_SERVER_DATA_DIR%"
if errorlevel 1 (echo The application stopped with an error.)
pause
