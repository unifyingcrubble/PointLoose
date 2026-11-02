@echo off
rem Builds PointLoose.exe. Needs Python 3.9+ from python.org (tick "Add python.exe to PATH").
setlocal
cd /d "%~dp0"

where py >nul 2>nul && (set "PY=py") || (set "PY=python")
%PY% --version >nul 2>nul
if errorlevel 1 (
  echo Python was not found. Install it from https://www.python.org/downloads/ and run this again.
  pause
  exit /b 1
)

echo Installing build tools...
%PY% -m pip install --upgrade pip pyinstaller segno bleak
if errorlevel 1 goto :fail

echo Building PointLoose.exe ...
%PY% -m PyInstaller --noconfirm --clean --onefile --windowed --noupx --collect-submodules bleak --collect-submodules winrt --name PointLoose --icon pointloose.ico --add-data "pointloose.ico;." pointloose_app.py
if errorlevel 1 goto :fail

echo.
echo Done. Your file is:  %~dp0dist\PointLoose.exe
echo You can send that single file to friends.
pause
exit /b 0

:fail
echo.
echo Something went wrong. Scroll up to read the error.
pause
exit /b 1
