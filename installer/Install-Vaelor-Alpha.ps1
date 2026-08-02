#Requires -Version 5.1
# Vaelor beginner installer - double-click INSTALL.bat
param(
  [string]$InstallDir = (Join-Path $env:LOCALAPPDATA "Vaelor"),
  [string]$SourceDir = "",
  [switch]$SkipShortcut,
  [switch]$OpenWhenDone,
  [switch]$Quiet
)

$ErrorActionPreference = "Stop"
$AlphaVersion = "1.1.0-alpha"
$script:LogPath = Join-Path $env:TEMP ("Vaelor-Install-" + (Get-Date -Format "yyyyMMdd-HHmmss") + ".log")

function Write-Log([string]$msg) {
  $line = "[{0}] {1}" -f (Get-Date -Format "HH:mm:ss"), $msg
  Add-Content -Path $script:LogPath -Value $line -ErrorAction SilentlyContinue
  if (-not $Quiet) { Write-Host $msg }
}
function Write-Step([string]$msg) {
  Write-Host ""
  Write-Host "  >> $msg" -ForegroundColor Cyan
  Write-Log $msg
}
function Write-Ok([string]$msg) {
  Write-Host "     OK: $msg" -ForegroundColor Green
  Write-Log "OK $msg"
}
function Write-WarnMsg([string]$msg) {
  Write-Host "     NOTE: $msg" -ForegroundColor Yellow
  Write-Log "NOTE $msg"
}
function Stop-Install([string]$msg) {
  Write-Host ""
  Write-Host "  Something went wrong." -ForegroundColor Red
  Write-Host "  $msg" -ForegroundColor Red
  Write-Host ""
  Write-Host "  A log was saved here:" -ForegroundColor Yellow
  Write-Host "  $script:LogPath"
  Write-Host "  You can send that file to whoever gave you Vaelor." -ForegroundColor Gray
  Write-Log "FAIL $msg"
  if (-not $Quiet) { try { Read-Host "Press Enter to close" | Out-Null } catch {} }
  exit 1
}
function Update-SessionPath {
  $machine = [Environment]::GetEnvironmentVariable("Path", "Machine")
  $user = [Environment]::GetEnvironmentVariable("Path", "User")
  $env:Path = (@($machine, $user) -join ";")
}
function Find-PythonExe {
  Update-SessionPath
  $candidates = @(
    @{ Cmd = "py"; Args = @("-3.12", "-c", "import sys;print(sys.executable)") },
    @{ Cmd = "py"; Args = @("-3.11", "-c", "import sys;print(sys.executable)") },
    @{ Cmd = "py"; Args = @("-3", "-c", "import sys;print(sys.executable)") },
    @{ Cmd = "python"; Args = @("-c", "import sys;print(sys.executable)") }
  )
  foreach ($item in $candidates) {
    try {
      $out = & $item.Cmd @($item.Args) 2>$null
      if ($LASTEXITCODE -eq 0 -and $out) {
        $path = ($out | Select-Object -First 1).ToString().Trim()
        if ($path -and (Test-Path $path) -and ($path -notmatch "WindowsApps\\python")) { return $path }
      }
    } catch {}
  }
  $guesses = @(
    (Join-Path $env:LOCALAPPDATA "Programs\Python\Python312\python.exe"),
    (Join-Path $env:LOCALAPPDATA "Programs\Python\Python311\python.exe"),
    (Join-Path $env:LOCALAPPDATA "Programs\Python\Python310\python.exe"),
    "C:\Python312\python.exe"
  )
  foreach ($g in $guesses) { if (Test-Path $g) { return $g } }
  return $null
}
function Install-PythonEasy {
  Write-Step "Python is missing. Vaelor will try to install it for you (free, official)."
  Write-Host "     This can take a few minutes. Please leave this window open." -ForegroundColor Gray
  $winget = Get-Command winget -ErrorAction SilentlyContinue
  if ($winget) {
    Write-Log "Trying winget Python.Python.3.12"
    try {
      $proc = Start-Process -FilePath "winget" -ArgumentList @(
        "install", "-e", "--id", "Python.Python.3.12",
        "--accept-package-agreements", "--accept-source-agreements",
        "--scope", "user", "--disable-interactivity"
      ) -Wait -PassThru -WindowStyle Hidden
      Write-Log ("winget exit " + $proc.ExitCode)
      Update-SessionPath
      $found = Find-PythonExe
      if ($found) { return $found }
    } catch { Write-Log ("winget failed: " + $_) }
  } else {
    Write-WarnMsg "Windows Package Manager not found; trying direct download."
  }
  $url = "https://www.python.org/ftp/python/3.12.10/python-3.12.10-amd64.exe"
  $tmp = Join-Path $env:TEMP "vaelor-python-setup.exe"
  try {
    Write-Step "Downloading Python from python.org ..."
    [Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12
    Invoke-WebRequest -Uri $url -OutFile $tmp -UseBasicParsing
    Write-Step "Installing Python (usually no admin needed) ..."
    $setupArgs = "/quiet InstallAllUsers=0 PrependPath=1 Include_test=0 Include_launcher=1 SimpleInstall=1"
    $proc = Start-Process -FilePath $tmp -ArgumentList $setupArgs -Wait -PassThru
    Write-Log ("python setup exit " + $proc.ExitCode)
    Start-Sleep -Seconds 2
    Update-SessionPath
    $found = Find-PythonExe
    if ($found) { return $found }
  } catch { Write-Log ("direct python install failed: " + $_) }
  return $null
}
function Copy-CoreTree {
  param([string]$From, [string]$To)
  if (-not (Test-Path $To)) { New-Item -ItemType Directory -Path $To -Force | Out-Null }
  $excludeDirs = @(".venv", "__pycache__", ".pytest_cache", ".git", "node_modules", ".staging", "dist")
  $excludeFiles = @("*.pyc", "*.pyo", ".coverage", "_access_ok.txt")
  $rcArgs = @($From, $To, "/E", "/NFL", "/NDL", "/NJH", "/NJS", "/nc", "/ns", "/np")
  foreach ($d in $excludeDirs) { $rcArgs += @("/XD", $d) }
  foreach ($f in $excludeFiles) { $rcArgs += @("/XF", $f) }
  & robocopy @rcArgs | Out-Null
  if ($LASTEXITCODE -ge 8) { throw "Could not copy Vaelor files (code $LASTEXITCODE)" }
}
function Write-EasyLauncher {
  param([string]$TargetDir)
  $bat = Join-Path $TargetDir "Start-Vaelor.bat"
  @(
    "@echo off",
    "setlocal",
    "cd /d `"%~dp0`"",
    "title Vaelor",
    "echo.",
    "echo  Starting Vaelor (Vay-lore)...",
    "echo  A browser window should open. Keep THIS window open while you use Vaelor.",
    "echo  To quit: close this window.",
    "echo.",
    "if not exist `".venv\Scripts\python.exe`" (",
    "  echo Vaelor is not fully installed.",
    "  echo Double-click INSTALL.bat again.",
    "  pause",
    "  exit /b 1",
    ")",
    "start `"`" `"http://localhost:8000`"",
    "`".venv\Scripts\python.exe`" -m uvicorn api.server:app --host localhost --port 8000",
    "echo.",
    "echo Vaelor stopped.",
    "pause"
  ) | Set-Content -Path $bat -Encoding ASCII

  $how = Join-Path $TargetDir "HOW-TO-USE.txt"
  @(
    "VAELOR (say: Vay-lore) - How to use",
    "====================================",
    "",
    "START",
    "1. Double-click the desktop icon:  Vaelor",
    "2. Wait a few seconds. Your web browser opens.",
    "3. Click the closed book (tome) to open Vaelor.",
    "4. Type a message, or click Summon Call to talk with your mic",
    "   (Chrome or Edge works best).",
    "",
    "STOP",
    "- Close the black window titled Vaelor.",
    "",
    "OPTIONAL BRAIN",
    "Install free Ollama: https://ollama.com/download",
    "Then open Setup inside Vaelor.",
    "",
    "HELP",
    "Send Temp log Vaelor-Install-....log plus a screenshot.",
    "",
    "Name: Vay-lore. Free. Local. No subscription."
  ) | Set-Content -Path $how -Encoding UTF8
  return $bat
}

Clear-Host
Write-Host ""
Write-Host "  ================================================" -ForegroundColor DarkYellow
Write-Host "     VAELOR  (say: Vay-lore)" -ForegroundColor Cyan
Write-Host "     Easy Installer  $AlphaVersion" -ForegroundColor Cyan
Write-Host "     Free local AI companion" -ForegroundColor Gray
Write-Host "  ================================================" -ForegroundColor DarkYellow
Write-Host ""
Write-Host "  You do not need to know coding." -ForegroundColor White
Write-Host "  This will set everything up and put a shortcut on your Desktop." -ForegroundColor White
Write-Host "  Log: $script:LogPath" -ForegroundColor DarkGray
Write-Host ""
Write-Log "Install start version=$AlphaVersion"

try {
  if (-not $SourceDir) {
    $SourceDir = Split-Path -Parent $PSScriptRoot
    if (-not (Test-Path (Join-Path $SourceDir "api\server.py"))) { $SourceDir = $PSScriptRoot }
  }
  if (-not [System.IO.Path]::IsPathRooted($SourceDir)) { $SourceDir = Join-Path (Get-Location) $SourceDir }
  $SourceDir = (Resolve-Path $SourceDir).Path
  if (-not (Test-Path (Join-Path $SourceDir "api\server.py"))) {
    Stop-Install "Could not find Vaelor files. Unzip the whole folder, then double-click INSTALL.bat inside it."
  }

  Write-Step "Step 1 of 5 - Checking for Python (the free engine Vaelor needs)"
  $pythonExe = Find-PythonExe
  if (-not $pythonExe) { $pythonExe = Install-PythonEasy }
  if (-not $pythonExe) {
    Stop-Install "Python could not be installed automatically.`r`n`r`nPlease do this once, then run INSTALL again:`r`n1) Open https://www.python.org/downloads/`r`n2) Click the big yellow Download button`r`n3) Run the installer`r`n4) CHECK THE BOX: Add python.exe to PATH`r`n5) Click Install Now`r`n6) Double-click INSTALL.bat again"
  }
  Write-Ok "Python ready"

  Write-Step "Step 2 of 5 - Copying Vaelor to your computer"
  Write-Host "     Folder: $InstallDir" -ForegroundColor DarkGray
  Copy-CoreTree -From $SourceDir -To $InstallDir
  Write-Ok "Files copied"

  Write-Step "Step 3 of 5 - Creating Vaelor private workspace"
  $venvPy = Join-Path $InstallDir ".venv\Scripts\python.exe"
  if (-not (Test-Path $venvPy)) {
    & $pythonExe -m venv (Join-Path $InstallDir ".venv")
    if ($LASTEXITCODE -ne 0 -or -not (Test-Path (Join-Path $InstallDir ".venv\Scripts\python.exe"))) {
      Stop-Install "Could not create Vaelor workspace. Restart your PC and run INSTALL again."
    }
  }
  $venvPy = Join-Path $InstallDir ".venv\Scripts\python.exe"
  Write-Ok "Workspace ready"

  Write-Step "Step 4 of 5 - Installing Vaelor parts (internet needed, a few minutes)"
  & $venvPy -m pip install --upgrade pip setuptools wheel 2>&1 | Out-Null
  $req = Join-Path $InstallDir "requirements.txt"
  if (Test-Path $req) {
    & $venvPy -m pip install -r $req
    if ($LASTEXITCODE -ne 0) { Stop-Install "Could not download Vaelor parts. Check your internet and try again." }
  } else {
    & $venvPy -m pip install "fastapi>=0.115" "uvicorn>=0.30" "pydantic>=2" "requests>=2.32" "psutil>=5.9" "edge-tts>=6.1.9" "anyio>=4"
    if ($LASTEXITCODE -ne 0) { Stop-Install "Could not download Vaelor parts. Check your internet and try again." }
  }
  Write-Ok "Parts installed"

  
  
  Write-Step "Creating settings for THIS computer only"
  $initPy = Join-Path $InstallDir "installer\init_local_config.py"
  if (-not (Test-Path $initPy)) { $initPy = Join-Path $SourceDir "installer\init_local_config.py" }
  if (Test-Path $initPy) {
    # Ensure templates exist in install dir
    $tplDst = Join-Path $InstallDir "config\templates"
    $tplSrc = Join-Path $SourceDir "config\templates"
    New-Item -ItemType Directory -Path $tplDst -Force | Out-Null
    if (Test-Path $tplSrc) { Copy-Item (Join-Path $tplSrc "*") $tplDst -Force -Recurse }
    $initOut = & $venvPy $initPy $InstallDir --force 2>&1
    Write-Log ("init_local_config: " + ($initOut -join " | "))
    Write-Ok "Local paths, free port, and empty memory prepared for this PC"
  } else {
    Write-WarnMsg "Local config initializer missing; desktop app will still auto-pick a port."
  }
Write-Step "Reserving a free local port for this install"
  $bindPy = Join-Path $InstallDir "installer\bind_network.py"
  if (-not (Test-Path $bindPy)) { $bindPy = Join-Path $SourceDir "installer\bind_network.py" }
  if (Test-Path $bindPy) {
    $bindOut = & $venvPy $bindPy $InstallDir 2>&1
    Write-Log ("network bind: " + ($bindOut -join " | "))
    Write-Ok ("Local address reserved: " + (($bindOut | Select-Object -First 1)))
  } else {
    Write-WarnMsg "Port binder missing; Vaelor will pick a free port on first launch."
  }
Write-Step "Step 5 of 5 - Desktop shortcut and Start menu"
  $startBat = Write-EasyLauncher -TargetDir $InstallDir
  @{
    product = "Vaelor"
    version = $AlphaVersion
    installed_at = (Get-Date).ToString("o")
    source = $SourceDir
    install_dir = $InstallDir
    beginner = $true
  } | ConvertTo-Json | Set-Content (Join-Path $InstallDir "VERSION.json") -Encoding UTF8

  if (-not $SkipShortcut) {
    $wshell = New-Object -ComObject WScript.Shell
    $desktop = [Environment]::GetFolderPath("Desktop")
    $lnkPath = Join-Path $desktop "Vaelor.lnk"
    $sc = $wshell.CreateShortcut($lnkPath)
    $sc.TargetPath = $startBat
    $sc.WorkingDirectory = $InstallDir
    $sc.Description = "Vaelor (Vay-lore) - free local AI"
    $sc.Save()
    Write-Ok "Desktop icon: Vaelor"
    $startMenu = Join-Path $env:APPDATA "Microsoft\Windows\Start Menu\Programs"
    if (Test-Path $startMenu) {
      $sm = Join-Path $startMenu "Vaelor.lnk"
      $sc2 = $wshell.CreateShortcut($sm)
      $sc2.TargetPath = $startBat
      $sc2.WorkingDirectory = $InstallDir
      $sc2.Description = "Vaelor"
      $sc2.Save()
      Write-Ok "Start menu: Vaelor"
    }
  }

  Write-Host ""
  Write-Host "  ================================================" -ForegroundColor Green
  Write-Host "     ALL DONE - Vaelor is installed!" -ForegroundColor Green
  Write-Host "  ================================================" -ForegroundColor Green
  Write-Host ""
  Write-Host "  What to do now:" -ForegroundColor Cyan
  Write-Host "    1. Double-click the desktop icon named  Vaelor" -ForegroundColor White
  Write-Host "    2. Wait for the browser to open" -ForegroundColor White
  Write-Host "    3. Click the closed book to open the archive" -ForegroundColor White
  Write-Host ""
  Write-Host "  Optional (makes Vaelor smarter):" -ForegroundColor Yellow
  Write-Host "    Install free Ollama from https://ollama.com/download" -ForegroundColor Gray
  Write-Host "    Then open Setup inside Vaelor." -ForegroundColor Gray
  Write-Host ""
  Write-Host "  Read: $InstallDir\HOW-TO-USE.txt" -ForegroundColor DarkGray
  Write-Host "  Installed to: $InstallDir" -ForegroundColor DarkGray
  Write-Host ""
  Write-Log "Install complete"

  if ($OpenWhenDone) {
    Write-Host "  Starting Vaelor now..." -ForegroundColor Cyan
    Start-Process $startBat
  } else {
    $ans = Read-Host "  Start Vaelor now? (Y/n)"
    if ($ans -eq "" -or $ans -match '^[Yy]') { Start-Process $startBat }
  }
  exit 0
}
catch {
  Stop-Install $_.Exception.Message
}


