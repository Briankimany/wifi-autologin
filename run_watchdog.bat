@echo off
REM Run one watchdog pass using the project's Windows virtual environment.
setlocal
set "ROOT=%~dp0"
if not exist "%ROOT%.venv\Scripts\python.exe" (
  echo Virtual environment not found. Run install_windows.ps1 first.
  exit /b 1
)
"%ROOT%.venv\Scripts\python.exe" "%ROOT%watchdog\watchdog.py" --run %*
endlocal
