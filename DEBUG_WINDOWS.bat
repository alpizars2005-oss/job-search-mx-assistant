@echo off
setlocal EnableExtensions
cd /d "%~dp0"

set "LOG_FILE=%CD%\jobsearch-debug.log"
>"%LOG_FILE%" echo Job Search Assistant debug log
>>"%LOG_FILE%" echo Date: %DATE% %TIME%
>>"%LOG_FILE%" echo Folder: %CD%
>>"%LOG_FILE%" echo.

if not exist ".venv\Scripts\python.exe" (
    echo The virtual environment was not found.
    echo Open START_WINDOWS.bat first; it now installs and starts everything automatically.
    >>"%LOG_FILE%" echo ERROR: .venv\Scripts\python.exe was not found.
    pause
    exit /b 1
)

echo Running installation diagnostics...
".venv\Scripts\python.exe" -m jobsearch_assistant doctor >>"%LOG_FILE%" 2>&1
set "DOCTOR_CODE=%ERRORLEVEL%"

echo Checking Tkinter...
".venv\Scripts\python.exe" -c "import tkinter; print('Tkinter OK', tkinter.TkVersion)" >>"%LOG_FILE%" 2>&1
set "TK_CODE=%ERRORLEVEL%"

echo Starting the GUI and recording all output...
".venv\Scripts\python.exe" -X faulthandler -m jobsearch_assistant gui >>"%LOG_FILE%" 2>&1
set "GUI_CODE=%ERRORLEVEL%"

>>"%LOG_FILE%" echo.
>>"%LOG_FILE%" echo doctor_exit_code=%DOCTOR_CODE%
>>"%LOG_FILE%" echo tkinter_exit_code=%TK_CODE%
>>"%LOG_FILE%" echo gui_exit_code=%GUI_CODE%

echo.
echo The application stopped or was closed.
echo Debug information was saved here:
echo %LOG_FILE%
echo.
type "%LOG_FILE%"
echo.
pause
exit /b %GUI_CODE%
