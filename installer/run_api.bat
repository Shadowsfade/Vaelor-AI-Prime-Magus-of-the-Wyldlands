@echo off
setlocal
cd /d "%~dp0.."
set "VAELOR_HOST=%~1"
set "VAELOR_PORT=%~2"
if not defined VAELOR_HOST set "VAELOR_HOST=localhost"
if not defined VAELOR_PORT set "VAELOR_PORT=8765"
".venv\Scripts\python.exe" -m uvicorn api.server:app --host "%VAELOR_HOST%" --port "%VAELOR_PORT%" >> "%TEMP%\vaelor-api.log" 2>&1
