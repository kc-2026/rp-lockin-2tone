@echo off
REM Launch the bench GUI with the project's venv, from the project directory.
REM
REM Both of those matter. On 2026-08-28 the GUI was started from a stale copy
REM on the Desktop using the system Python and failed with "No module named
REM numpy" -- neither the folder nor the interpreter was the right one, and the
REM error named only the second.
cd /d "%~dp0"
if not exist ".venv\Scripts\python.exe" (
  echo No .venv here. Create it with:
  echo    python -m venv .venv ^&^& .venv\Scripts\python -m pip install -e ".[dev]"
  pause
  exit /b 1
)
".venv\Scripts\python.exe" "scripts\bench_gui.py" %*
if errorlevel 1 pause
