@echo off
setlocal EnableDelayedExpansion
cd /d "%~dp0"
title Vaelor
echo.
echo  Starting Vaelor (Vay-lore)...
echo  Starting the persistent Vaelor API...
echo.
if not exist ".venv\Scripts\python.exe" (
  echo Vaelor is not fully installed. Run INSTALL.bat again.
  pause
  exit /b 1
)
set "VAELOR_HOST=localhost"
set "VAELOR_PORT=8765"
for /f "tokens=1,2 delims=:" %%H in ('".venv\Scripts\python.exe" installer\bind_network.py "%~dp0" 2^>nul') do (
  set "VAELOR_HOST=%%H"
  set "VAELOR_PORT=%%I"
)
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0installer\Start-Vaelor-Persistent.ps1" -Root "%~dp0" -BindHost "!VAELOR_HOST!" -Port "!VAELOR_PORT!"
if errorlevel 1 (
  echo Failed to start the persistent Vaelor API.
  pause
  exit /b 1
)
echo  Vaelor is running at http://!VAELOR_HOST!:!VAELOR_PORT!/
start "" "http://!VAELOR_HOST!:!VAELOR_PORT!/"
echo  This window may now close; the API is owned by Windows Task Scheduler.
exit /b 0
