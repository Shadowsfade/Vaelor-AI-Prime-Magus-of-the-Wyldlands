@echo off
setlocal EnableDelayedExpansion
cd /d "%~dp0"
title Vaelor
echo.
echo  Starting Vaelor (Vay-lore)...
echo  Keep THIS window open while you use Vaelor.
echo.
if not exist ".venv\Scripts\python.exe" (
  echo Vaelor is not fully installed. Run INSTALL.bat again.
  pause
  exit /b 1
)
set "VAELOR_HOST=localhost"
set "VAELOR_PORT=8765"
".venv\Scripts\python.exe" installer\bind_network.py "%~dp0" > "%TEMP%\vaelor-bind.txt" 2>nul
set /p VAELOR_BIND=<"%TEMP%\vaelor-bind.txt"
for /f "tokens=1,2 delims=:" %%H in ("!VAELOR_BIND!") do (
  set "VAELOR_HOST=%%H"
  set "VAELOR_PORT=%%I"
)
echo  Using local address: !VAELOR_HOST!:!VAELOR_PORT!
start "" "http://!VAELOR_HOST!:!VAELOR_PORT!/"
".venv\Scripts\python.exe" -m uvicorn api.server:app --host !VAELOR_HOST! --port !VAELOR_PORT!
echo.
echo Vaelor stopped.
pause
