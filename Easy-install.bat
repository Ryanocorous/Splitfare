@echo off
setlocal EnableExtensions
cd /d "%~dp0"

echo.
echo ========================================
echo SplitFare Easy Install
echo ========================================
echo.

where py >nul 2>nul
if errorlevel 1 (
    echo Python launcher "py" was not found.
    echo Install Python 3.12 from https://www.python.org/downloads/
    pause
    exit /b 1
)

if not exist "venv\Scripts\python.exe" (
    echo Creating virtual environment...
    py -3.12 -m venv venv
    if errorlevel 1 (
        echo Python 3.12 was not found. Trying default Python...
        py -m venv venv
    )
)

if not exist "venv\Scripts\python.exe" (
    echo Failed to create venv.
    pause
    exit /b 1
)

echo Upgrading pip...
"venv\Scripts\python.exe" -m pip install --upgrade pip
if errorlevel 1 goto install_error

echo Installing dependencies from requirements.txt...
"venv\Scripts\pip.exe" install -r requirements.txt
if errorlevel 1 goto install_error

echo Running quick tests...
"venv\Scripts\python.exe" -m unittest discover -s tests -v
if errorlevel 1 (
    echo.
    echo Dependencies installed, but tests reported a problem.
    echo You can still try run.bat, or send the test output for debugging.
    pause
    exit /b 1
)

echo.
echo Install complete. Run run.bat to start the browser app.
echo.
pause
exit /b 0

:install_error
echo.
echo Install failed. Check the error above.
echo Try running this manually:
echo   venv\Scripts\python.exe -m pip install -r requirements.txt
echo.
pause
exit /b 1
