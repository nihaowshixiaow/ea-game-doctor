@echo off
rem ---------------------------------------------------------------------------
rem  EA Game Doctor launcher
rem  Uses the bundled virtual environment; creates it on first run.
rem  This file is ASCII-only on purpose: cmd.exe decodes .bat with the OEM code
rem  page, so non-ASCII text here would corrupt the script on some systems.
rem ---------------------------------------------------------------------------
setlocal
cd /d "%~dp0"

if exist ".venv\Scripts\pythonw.exe" goto :launch

echo [EA Game Doctor] First run: preparing Python environment...
set "PYTHON_CMD="
where py >nul 2>nul && set "PYTHON_CMD=py -3"
if not defined PYTHON_CMD (
  where python >nul 2>nul && set "PYTHON_CMD=python"
)
if not defined PYTHON_CMD (
  echo Python was not found. Please install Python 3.10+ and run this file again.
  pause
  exit /b 1
)

%PYTHON_CMD% -m venv .venv
if errorlevel 1 (
  echo Failed to create the virtual environment.
  pause
  exit /b 1
)

if exist ".wheels" (
  ".venv\Scripts\python.exe" -m pip install --no-index --find-links ".wheels" --disable-pip-version-check PySide6-Essentials==6.12.0 shiboken6==6.12.0 psutil
) else (
  ".venv\Scripts\python.exe" -m pip install --disable-pip-version-check PySide6-Essentials==6.12.0 psutil
)
if errorlevel 1 (
  echo Dependency installation failed. Check your network / proxy and retry.
  pause
  exit /b 1
)

:launch
start "" ".venv\Scripts\pythonw.exe" "main.py" %*
exit /b 0
