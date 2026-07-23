@echo off
setlocal EnableExtensions
cd /d "%~dp0"
title Job Search Assistant

set "LOG_FILE=%CD%\jobsearch-startup.log"
set "ERROR_FILE=%TEMP%\jobsearch-gui-error-%RANDOM%.log"
set "VENV_PYTHON=%CD%\.venv\Scripts\python.exe"
set "PYTHON_CMD="

> "%LOG_FILE%" echo Job Search Assistant startup log
>> "%LOG_FILE%" echo Started: %DATE% %TIME%
>> "%LOG_FILE%" echo Folder: %CD%
>> "%LOG_FILE%" echo.

echo ==================================================
echo       JOB SEARCH ASSISTANT - ONE CLICK START
echo ==================================================
echo.
echo This window will prepare and open the application.
echo Keep it open while the program is starting.
echo.

rem Reuse a healthy virtual environment when one already exists.
if exist "%VENV_PYTHON%" (
    "%VENV_PYTHON%" --version >> "%LOG_FILE%" 2>&1
    if errorlevel 1 (
        echo The existing virtual environment is damaged. Rebuilding it...
        >> "%LOG_FILE%" echo Existing virtual environment failed its health check.
        rmdir /s /q ".venv" >> "%LOG_FILE%" 2>&1
    )
)

rem Find a system Python only when a virtual environment must be created.
if not exist "%VENV_PYTHON%" (
    where py >nul 2>&1
    if not errorlevel 1 set "PYTHON_CMD=py -3"

    if not defined PYTHON_CMD (
        where python >nul 2>&1
        if not errorlevel 1 set "PYTHON_CMD=python"
    )

    if not defined PYTHON_CMD goto :python_missing

    echo [1/5] Checking Python...
    %PYTHON_CMD% -c "import sys; raise SystemExit(0 if sys.version_info >= (3, 10) else 1)" >> "%LOG_FILE%" 2>&1
    if errorlevel 1 goto :python_too_old

    echo [2/5] Creating the private environment...
    %PYTHON_CMD% -m venv ".venv" >> "%LOG_FILE%" 2>&1
    if errorlevel 1 goto :failed
)

rem Install only when the editable package is missing. Source updates are picked up automatically.
echo [3/5] Checking the application installation...
"%VENV_PYTHON%" -c "import jobsearch_assistant" >> "%LOG_FILE%" 2>&1
if errorlevel 1 (
    echo Installing Job Search Assistant for the first time...
    "%VENV_PYTHON%" -m pip install --disable-pip-version-check --no-deps -e . >> "%LOG_FILE%" 2>&1
    if errorlevel 1 goto :failed
    "%VENV_PYTHON%" -m jobsearch_assistant init --language es >> "%LOG_FILE%" 2>&1
    if errorlevel 1 goto :failed
) else (
    echo Application installation found.
)

rem Tkinter is required for the desktop window.
echo [4/5] Checking the desktop interface...
"%VENV_PYTHON%" -c "import tkinter; print('Tkinter', tkinter.TkVersion)" >> "%LOG_FILE%" 2>&1
if errorlevel 1 goto :tkinter_missing

rem Validate configuration and SQLite before opening the GUI.
echo [5/5] Running diagnostics...
"%VENV_PYTHON%" -m jobsearch_assistant doctor
if errorlevel 1 goto :failed

>> "%LOG_FILE%" echo Diagnostics completed successfully.

rem Used by GitHub Actions and advanced users to validate setup without opening a window.
if /I "%JOBSEARCH_PREPARE_ONLY%"=="1" (
    echo Preparation completed successfully.
    >> "%LOG_FILE%" echo Preparation-only mode completed successfully.
    exit /b 0
)

>> "%LOG_FILE%" echo Opening GUI at %DATE% %TIME%.

echo.
echo Opening Job Search Assistant...
echo You may minimize this console while the app is open.
echo.

"%VENV_PYTHON%" -X faulthandler -m jobsearch_assistant gui 2> "%ERROR_FILE%"
set "APP_EXIT=%ERRORLEVEL%"

if exist "%ERROR_FILE%" (
    type "%ERROR_FILE%" >> "%LOG_FILE%"
)

if not "%APP_EXIT%"=="0" (
    echo.
    echo The application closed because of an error:
    echo --------------------------------------------------
    if exist "%ERROR_FILE%" type "%ERROR_FILE%"
    echo --------------------------------------------------
    goto :failed
)

if exist "%ERROR_FILE%" del /q "%ERROR_FILE%" >nul 2>&1
exit /b 0

:python_missing
echo.
echo [ERROR] Python 3.10 or newer was not found.
echo Install Python and enable "Add Python to PATH", then open this file again.
echo Download: https://www.python.org/downloads/windows/
>> "%LOG_FILE%" echo ERROR: Python was not found.
if /I not "%JOBSEARCH_NONINTERACTIVE%"=="1" start "" "https://www.python.org/downloads/windows/" >nul 2>&1
goto :pause_error

:python_too_old
echo.
echo [ERROR] Your Python version is older than 3.10.
echo Install a current Python version, then open this file again.
>> "%LOG_FILE%" echo ERROR: Python is older than 3.10.
goto :pause_error

:tkinter_missing
echo.
echo [ERROR] This Python installation does not include Tkinter.
echo Reinstall Python from python.org and keep the Tcl/Tk option enabled.
>> "%LOG_FILE%" echo ERROR: Tkinter is unavailable.
goto :pause_error

:failed
echo.
echo ==================================================
echo   Job Search Assistant could not start.
echo ==================================================
echo The complete report was saved here:
echo %LOG_FILE%
echo.
echo You can open it with:
echo notepad "%LOG_FILE%"

:pause_error
if exist "%ERROR_FILE%" del /q "%ERROR_FILE%" >nul 2>&1
if /I "%JOBSEARCH_NONINTERACTIVE%"=="1" exit /b 1
pause
exit /b 1
