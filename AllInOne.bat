@echo off
setlocal EnableExtensions
cd /d "%~dp0"

if exist ".venv\" goto :activate

echo ============================================
echo   First-time setup, please wait...
echo   Creating virtual environment and installing
echo   dependencies. This only runs once.
echo ============================================
echo.

where py >nul 2>&1
if not errorlevel 1 (
  py -3 -m venv .venv
) else (
  python -m venv .venv
)
if errorlevel 1 (
  echo Failed to create .venv. Is Python 3 installed and on PATH?
  pause
  exit /b 1
)

call ".venv\Scripts\activate.bat"
python -m pip install --upgrade pip
if errorlevel 1 (
  echo Failed to upgrade pip.
  pause
  exit /b 1
)
pip install -r requirements.txt
if errorlevel 1 (
  echo Failed to install requirements.
  pause
  exit /b 1
)
echo.
echo Setup complete.
echo.
goto :run

:activate
call ".venv\Scripts\activate.bat"

:run
echo Starting AllInOne...
echo A browser window should open automatically.
echo Leave this window open while using the app.
echo Press Ctrl+C to stop.
echo.

python app.py
if errorlevel 1 (
  echo.
  echo AllInOne exited with an error.
  pause
  exit /b 1
)
endlocal
