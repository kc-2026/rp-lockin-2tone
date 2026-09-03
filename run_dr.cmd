@echo off
rem Dynamic-range bench -- APD gain study. Separate from run_bench.cmd.
"%~dp0.venv\Scripts\python.exe" "%~dp0scripts\dr_bench.py" %*
