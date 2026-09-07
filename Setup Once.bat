@echo off
setlocal EnableExtensions
cd /d "%~dp0"

echo ============================================
echo   AllInOne setup
echo   Creating/updating .venv and installing deps
echo ============================================
echo.

if exist ".venv\" goto :install

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

:install
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
echo Setup complete. You can double-click AllInOne.bat to launch.
pause
endlocal
