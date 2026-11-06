@echo off
setlocal EnableExtensions
cd /d "%~dp0"
title AI App Server - Install
if not exist "%~dp0tools\portable_install.py" (
    echo ERROR: Extract the COMPLETE project ZIP before installing.
    pause
    exit /b 1
)
where py >nul 2>nul
if errorlevel 1 goto :try_python
py -3 -c "import sys; sys.exit(0 if sys.version_info >= (3,11) else 1)" >nul 2>nul
if not errorlevel 1 goto :using_py
:try_python
where python >nul 2>nul
if errorlevel 1 goto :missing_python
python -c "import sys; sys.exit(0 if sys.version_info >= (3,11) else 1)" >nul 2>nul
if errorlevel 1 goto :missing_python
python "%~dp0tools\portable_install.py" %*
set "RESULT=%ERRORLEVEL%"
if not "%RESULT%"=="0" pause
exit /b %RESULT%
:using_py
py -3 "%~dp0tools\portable_install.py" %*
set "RESULT=%ERRORLEVEL%"
if not "%RESULT%"=="0" pause
exit /b %RESULT%
:missing_python
echo ERROR: Python 3.11 or newer is required.
echo Download Python from https://www.python.org/downloads/windows/
echo After installing Python, run INSTALL.bat again.
pause
exit /b 1
