@echo off
setlocal
cd /d "%~dp0"
title AI App Server - Safe Engine Updater
echo.
echo  ==============================================
echo    AI APP SERVER - UPDATE ENGINE ONLY
echo  ==============================================
echo.
echo  Select your downloaded AI App Server update ZIP.
echo  Your application, database and settings are preserved.
echo.
if not exist ".venv\Scripts\python.exe" (
  echo ERROR: This installation is not ready yet. Run START HERE.bat first.
  goto :failed
)
".venv\Scripts\python.exe" tools\update_engine.py
if errorlevel 1 goto :failed
echo.
echo  Update process finished.
pause
exit /b 0
:failed
echo.
echo  The engine update was not completed. Your current installation was retained or restored; check the error above.
pause
exit /b 1
