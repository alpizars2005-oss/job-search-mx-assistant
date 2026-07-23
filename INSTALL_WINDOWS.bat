@echo off
setlocal EnableExtensions
cd /d "%~dp0"

echo INSTALL_WINDOWS.bat is now included in the one-click launcher.
echo Starting START_WINDOWS.bat...
echo.
call "%~dp0START_WINDOWS.bat"
exit /b %ERRORLEVEL%
