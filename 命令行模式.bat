@echo off
rem CLI mode: run diagnostics / scan / repair-plan without the GUI.
rem ASCII-only for cmd.exe compatibility.
setlocal
cd /d "%~dp0"
if not exist ".venv\Scripts\python.exe" (
  echo Please run the GUI launcher once to prepare the environment first.
  pause
  exit /b 1
)
".venv\Scripts\python.exe" "main.py" %*
pause
