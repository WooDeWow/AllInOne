@echo off
REM Local / CI Windows packaging with PyInstaller (onedir).
REM Gradio apps are flaky under PyInstaller; prefer AllInOne.bat for coworkers.
setlocal EnableExtensions
cd /d "%~dp0\.."

python -m pip install --upgrade pip
if errorlevel 1 exit /b 1
pip install -r requirements.txt
if errorlevel 1 exit /b 1
pip install "pyinstaller>=6.0,<7"
if errorlevel 1 exit /b 1

if exist build rmdir /s /q build
if exist dist rmdir /s /q dist
if exist AllInOne.spec del /f /q AllInOne.spec

pyinstaller ^
  --noconfirm ^
  --clean ^
  --onedir ^
  --name AllInOne ^
  --console ^
  --collect-all gradio ^
  --collect-all gradio_client ^
  --hidden-import utils ^
  --hidden-import utils.common ^
  --hidden-import utils.images ^
  --hidden-import utils.license ^
  --hidden-import utils.pdf_tools ^
  --hidden-import pikepdf ^
  --hidden-import pypdf ^
  --hidden-import pdf2docx ^
  --hidden-import PIL ^
  app.py
if errorlevel 1 exit /b 1

echo.
echo Built: dist\AllInOne\
echo Run:   dist\AllInOne\AllInOne.exe
echo Note: packaged Gradio builds are experimental; coworkers should use AllInOne.bat.
endlocal
