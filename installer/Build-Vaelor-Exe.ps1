#Requires -Version 5.1
# Build a real Vaelor.exe desktop app (native window + local server)
param(
  [string]$SourceDir = ""
)

$ErrorActionPreference = "Stop"
if (-not $SourceDir) { $SourceDir = Split-Path -Parent $PSScriptRoot }
$SourceDir = (Resolve-Path $SourceDir).Path
Set-Location $SourceDir

$py = Join-Path $SourceDir ".venv\Scripts\python.exe"
if (-not (Test-Path $py)) { throw "Missing .venv. Create venv and install requirements first." }

Write-Host "Installing build deps..."
& $py -m pip install -q pyinstaller pywebview

$distDir = Join-Path $SourceDir "dist"
$workDir = Join-Path $SourceDir "build\pyinstaller"
New-Item -ItemType Directory -Path $distDir -Force | Out-Null
New-Item -ItemType Directory -Path $workDir -Force | Out-Null

$entry = Join-Path $SourceDir "desktop\vaelor_app.py"
if (-not (Test-Path $entry)) { throw "Missing desktop\vaelor_app.py" }

Write-Host "Building Vaelor.exe (this can take several minutes)..."
# onedir build keeps api/web/.venv usable beside the exe after we stage them
& $py -m PyInstaller `
  --noconfirm `
  --clean `
  --windowed `
  --name "Vaelor" `
  --distpath $distDir `
  --workpath $workDir `
  --specpath $workDir `
  --hidden-import uvicorn `
  --hidden-import uvicorn.logging `
  --hidden-import uvicorn.loops `
  --hidden-import uvicorn.loops.auto `
  --hidden-import uvicorn.protocols `
  --hidden-import uvicorn.protocols.http `
  --hidden-import uvicorn.protocols.http.auto `
  --hidden-import uvicorn.protocols.websockets `
  --hidden-import uvicorn.protocols.websockets.auto `
  --hidden-import uvicorn.lifespan `
  --hidden-import uvicorn.lifespan.on `
  --hidden-import fastapi `
  --hidden-import starlette `
  --hidden-import edge_tts `
  --hidden-import webview `
  --collect-all webview `
  $entry

$outDir = Join-Path $distDir "Vaelor"
if (-not (Test-Path (Join-Path $outDir "Vaelor.exe"))) {
  throw "Build failed: Vaelor.exe not found in $outDir"
}

# Stage runtime tree next to exe so server can import api/ and serve web/
$copyDirs = @("api", "core", "spellbook", "web", "config", "installer")
foreach ($d in $copyDirs) {
  $src = Join-Path $SourceDir $d
  $dst = Join-Path $outDir $d
  if (Test-Path $src) {
    Write-Host "Staging $d ..."
    if (Test-Path $dst) { Remove-Item $dst -Recurse -Force }
    robocopy $src $dst /E /XD __pycache__ .pytest_cache /NFL /NDL /NJH /NJS /nc /ns /np | Out-Null
  }
}

# Fresh memory skeleton
$mem = Join-Path $outDir "memory"
New-Item -ItemType Directory -Path $mem -Force | Out-Null
'[]' | Set-Content (Join-Path $mem "archive.json") -Encoding UTF8
'{}' | Set-Content (Join-Path $mem "conversations.json") -Encoding UTF8

# Copy requirements + readme
Copy-Item (Join-Path $SourceDir "requirements.txt") (Join-Path $outDir "requirements.txt") -Force -ErrorAction SilentlyContinue
@(
  "VAELOR DESKTOP",
  "Double-click Vaelor.exe",
  "A native window opens (not a browser tab).",
  "Keep the app open while you use Vaelor.",
  "Optional: install Ollama from https://ollama.com/download for a smarter brain."
) | Set-Content (Join-Path $outDir "HOW-TO-USE.txt") -Encoding UTF8

# Bundle a dedicated venv for the packaged app (server runtime)
$packVenv = Join-Path $outDir ".venv"
if (-not (Test-Path (Join-Path $packVenv "Scripts\python.exe"))) {
  Write-Host "Creating runtime venv beside Vaelor.exe ..."
  & $py -m venv $packVenv
  $packPy = Join-Path $packVenv "Scripts\python.exe"
  & $packPy -m pip install -q --upgrade pip
  & $packPy -m pip install -q -r (Join-Path $SourceDir "requirements.txt")
}

# Desktop shortcut helper script
$shortcutPs1 = Join-Path $outDir "Create-Desktop-Shortcut.ps1"
@"
`$exe = Join-Path `$PSScriptRoot 'Vaelor.exe'
`$desktop = [Environment]::GetFolderPath('Desktop')
`$lnk = Join-Path `$desktop 'Vaelor.lnk'
`$w = New-Object -ComObject WScript.Shell
`$s = `$w.CreateShortcut(`$lnk)
`$s.TargetPath = `$exe
`$s.WorkingDirectory = `$PSScriptRoot
`$s.Description = 'Vaelor (Vay-lore)'
`$s.Save()
Write-Host "Desktop shortcut created: `$lnk"
"@ | Set-Content $shortcutPs1 -Encoding UTF8

# Simple launcher bat for people who want it
@(
  "@echo off",
  "cd /d `"%~dp0`"",
  "start `"`" `"%~dp0Vaelor.exe`""
) | Set-Content (Join-Path $outDir "Start-Vaelor.bat") -Encoding ASCII


# SANITIZE personal machine config from desktop package
$cfg = Join-Path $outDir "config"
New-Item -ItemType Directory -Path (Join-Path $cfg "templates") -Force | Out-Null
$srcTemplates = Join-Path $SourceDir "config\templates"
if (Test-Path $srcTemplates) { Copy-Item (Join-Path $srcTemplates "*") (Join-Path $cfg "templates") -Force -Recurse }
foreach ($pair in @(
  @("templates\autonomy.portable.json","autonomy.json"),
  @("templates\vaelor.portable.json","vaelor.json"),
  @("templates\models.portable.json","models.json")
)) {
  $src = Join-Path $cfg $pair[0]
  if (Test-Path $src) { Copy-Item $src (Join-Path $cfg $pair[1]) -Force }
}
if (Test-Path (Join-Path $cfg "network.json")) { Remove-Item (Join-Path $cfg "network.json") -Force }
if (Test-Path (Join-Path $cfg "setup_complete.json")) { Remove-Item (Join-Path $cfg "setup_complete.json") -Force }
# Generate local config for the package folder as a starting point on THIS build machine only for smoke tests;
# real users re-run init on install.
$initPy = Join-Path $SourceDir "installer\init_local_config.py"
$packPy = Join-Path $outDir ".venv\Scripts\python.exe"
if ((Test-Path $initPy) -and (Test-Path $packPy)) {
  Copy-Item $initPy (Join-Path $outDir "installer\init_local_config.py") -Force
  # Do NOT force-bind builder identity into shipped package beyond templates.
}

# Port bind happens on the USER machine via installer/init_local_config + desktop app (not builder PC)
$bindScript = Join-Path $SourceDir "installer\bind_network.py"
$initScript = Join-Path $SourceDir "installer\init_local_config.py"
New-Item -ItemType Directory -Path (Join-Path $outDir "installer") -Force | Out-Null
if (Test-Path $bindScript) { Copy-Item $bindScript (Join-Path $outDir "installer\bind_network.py") -Force }
if (Test-Path $initScript) { Copy-Item $initScript (Join-Path $outDir "installer\init_local_config.py") -Force }
if (Test-Path (Join-Path $outDir "config\network.json")) { Remove-Item (Join-Path $outDir "config\network.json") -Force }

# Zip the onedir package for distribution
$zip = Join-Path $distDir "Vaelor-Desktop-1.1.4-alpha.zip"
if (Test-Path $zip) { Remove-Item $zip -Force }
Write-Host "Zipping $zip ..."
Compress-Archive -Path $outDir -DestinationPath $zip -Force
$hash = (Get-FileHash -Algorithm SHA256 $zip).Hash
$hash | Set-Content ($zip + ".sha256") -Encoding ASCII

Write-Host ""
Write-Host "DONE"
Write-Host "EXE:  $(Join-Path $outDir 'Vaelor.exe')"
Write-Host "ZIP:  $zip"
Write-Host "SHA:  $hash"
Write-Host "Size: $([math]::Round((Get-Item $zip).Length / 1MB, 1)) MB"


