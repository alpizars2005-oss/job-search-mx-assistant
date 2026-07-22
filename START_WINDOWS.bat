@echo off
setlocal EnableExtensions
cd /d "%~dp0"

if not exist ".venv\Scripts\python.exe" (
    echo Job Search Assistant is not installed yet.
    echo Starting the installer...
    echo.
    call INSTALL_WINDOWS.bat
    if errorlevel 1 exit /b 1
)

echo Checking the installation...
".venv\Scripts\python.exe" -m jobsearch_assistant doctor
if errorlevel 1 goto :failed

echo.
echo Opening Job Search Assistant...
".venv\Scripts\python.exe" -m jobsearch_assistant gui
if errorlevel 1 goto :failed
exit /b 0

:failed
echo.
echo ==================================================
echo   The application could not start.
echo   Copy or capture the error shown above.
echo ==================================================
echo.
pause
exit /b 1
