@echo off
REM Launch the PANEL bench with the project's venv, from the project directory.
REM
REM Both matter. Starting a GUI from a stale copy on the Desktop with the
REM system Python fails with "No module named numpy", which names the
REM interpreter but not the real problem, which is the folder.
REM
REM The old tabbed GUI is still here as run_gui.cmd until this one has earned
REM the bench.
cd /d "%~dp0"
if not exist ".venv\Scripts\python.exe" (
  echo No .venv here. Create it with:
  echo    python -m venv .venv ^&^& .venv\Scripts\python -m pip install -e ".[dev]"
  pause
  exit /b 1
)
".venv\Scripts\python.exe" "scripts\bench.py" %*
if errorlevel 1 pause
