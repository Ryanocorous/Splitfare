@echo off
setlocal EnableExtensions
cd /d "%~dp0"

echo.
echo ========================================
echo Starting SplitFare UK
echo ========================================
echo.

if not exist "venv\Scripts\python.exe" (
    echo Virtual environment not found.
    echo Running Easy-Install.bat first...
    call "%~dp0Easy-Install.bat"
    if errorlevel 1 exit /b 1
)

"venv\Scripts\python.exe" -m splitfare.web_app
pause
