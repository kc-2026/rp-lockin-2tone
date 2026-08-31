@echo off
REM Launch the PANEL bench with the project's venv, from the project dir.
REM The old tabbed GUI is still there as run_gui.cmd until this one has
REM earned the bench.
cd /d "%~dp0"
if not exist ".venv\Scripts\python.exe" (
  echo No .venv here. Create it with:
  echo    python -m venv .venv ^&^& .venv\Scripts\python -m pip install -e ".[dev]"
  pause
  exit /b 1
)
".venv\Scripts\python.exe" "scriptsench.py" %*
if errorlevel 1 pause
