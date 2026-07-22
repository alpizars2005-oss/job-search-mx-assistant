@echo off
setlocal EnableExtensions
cd /d "%~dp0"

echo ==================================================
echo   Job Search Assistant - Windows installation
echo ==================================================
echo.

set "PYTHON_CMD="
where py >nul 2>&1 && set "PYTHON_CMD=py"
if not defined PYTHON_CMD (
    where python >nul 2>&1 && set "PYTHON_CMD=python"
)

if not defined PYTHON_CMD (
    echo [ERROR] Python was not found.
    echo Install Python 3.10 or newer from https://www.python.org/downloads/
    echo During installation, enable "Add Python to PATH".
    echo.
    pause
    exit /b 1
)

echo [1/5] Python detected:
%PYTHON_CMD% --version
if errorlevel 1 goto :failed

echo.
echo [2/5] Creating the virtual environment...
if not exist ".venv\Scripts\python.exe" (
    %PYTHON_CMD% -m venv .venv
    if errorlevel 1 goto :failed
) else (
    echo Existing virtual environment found.
)

echo.
echo [3/5] Updating the installer tools...
".venv\Scripts\python.exe" -m pip install --upgrade pip setuptools wheel
if errorlevel 1 goto :failed

echo.
echo [4/5] Installing Job Search Assistant...
".venv\Scripts\python.exe" -m pip install -e .
if errorlevel 1 goto :failed

echo.
echo [5/5] Creating the local workspace and running diagnostics...
".venv\Scripts\python.exe" -m jobsearch_assistant init --language es
if errorlevel 1 goto :failed
".venv\Scripts\python.exe" -m jobsearch_assistant doctor
if errorlevel 1 goto :failed

echo.
echo ==================================================
echo   Installation completed successfully.
echo   Double-click START_WINDOWS.bat to open the app.
echo ==================================================
echo.
pause
exit /b 0

:failed
echo.
echo ==================================================
echo   Installation failed.
echo   Copy or capture the error shown above.
echo ==================================================
echo.
pause
exit /b 1
