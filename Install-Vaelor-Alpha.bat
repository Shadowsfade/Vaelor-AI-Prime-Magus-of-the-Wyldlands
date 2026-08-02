@echo off
setlocal
cd /d "%~dp0"
title Vaelor Easy Installer
color 0B
echo.
echo  ================================================
echo     VAELOR  (say: Vay-lore)
echo     Easy Installer - no coding needed
echo  ================================================
echo.
echo  Just wait - this window will set everything up.
echo  You need internet for the first install.
echo.
where pwsh >nul 2>&1
if %ERRORLEVEL%==0 (
  pwsh -NoProfile -ExecutionPolicy Bypass -File "%~dp0installer\Install-Vaelor-Alpha.ps1" -SourceDir "%~dp0" -OpenWhenDone
) else (
  powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0installer\Install-Vaelor-Alpha.ps1" -SourceDir "%~dp0" -OpenWhenDone
)
set ERR=%ERRORLEVEL%
if not %ERR%==0 (
  color 0C
  echo.
  echo  Install did not finish. Read the message above.
  echo  Or open the log file in your Temp folder named Vaelor-Install-...
  echo.
  pause
  exit /b %ERR%
)
echo.
pause
