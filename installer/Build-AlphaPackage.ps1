#Requires -Version 5.1
<#
.SYNOPSIS
  Build a portable Vaelor Alpha zip for testers (no .venv inside the zip).
#>
[CmdletBinding()]
param(
  [string]$OutDir = "",
  [string]$SourceDir = ""
)

$ErrorActionPreference = "Stop"
$AlphaVersion = "1.1.4-alpha"

if (-not $SourceDir) {
  $SourceDir = Split-Path -Parent $PSScriptRoot
}
$SourceDir = (Resolve-Path $SourceDir).Path
if (-not $OutDir) {
  $OutDir = Join-Path $SourceDir "dist"
}
New-Item -ItemType Directory -Path $OutDir -Force | Out-Null

$stage = Join-Path $env:TEMP ("vaelor-alpha-stage-" + [guid]::NewGuid().ToString("N"))
New-Item -ItemType Directory -Path $stage -Force | Out-Null

Write-Host "Staging from $SourceDir -> $stage"

$excludeDirNames = @(
  ".venv", "__pycache__", ".pytest_cache", ".git", "node_modules",
  ".staging", "dist", "memory"
)
# Include a clean memory placeholder; exclude live personal memory dumps from package
function Should-SkipDir([string]$name) {
  return $excludeDirNames -contains $name
}

function Copy-Filtered {
  param($From, $To)
  New-Item -ItemType Directory -Path $To -Force | Out-Null
  Get-ChildItem -LiteralPath $From -Force | ForEach-Object {
    if ($_.PSIsContainer) {
      if (Should-SkipDir $_.Name) { return }
      Copy-Filtered -From $_.FullName -To (Join-Path $To $_.Name)
    } else {
      if ($_.Extension -in @(".pyc", ".pyo")) { return }
      if ($_.Name -match '^(audit_log|conversations)\.json') { return }
      Copy-Item -LiteralPath $_.FullName -Destination (Join-Path $To $_.Name) -Force
    }
  }
}

$rootName = "Vaelor-Alpha-$AlphaVersion"
$payload = Join-Path $stage $rootName
Copy-Filtered -From $SourceDir -To $payload


# SANITIZE: strip personal machine config from package
$cfg = Join-Path $payload "config"
New-Item -ItemType Directory -Path (Join-Path $cfg "templates") -Force | Out-Null
$srcTemplates = Join-Path $SourceDir "config\templates"
if (Test-Path $srcTemplates) {
  Copy-Item (Join-Path $srcTemplates "*") (Join-Path $cfg "templates") -Force -Recurse
}
# Replace shipped configs with portable templates / empty local state
$portableAutonomy = Join-Path $cfg "templates\autonomy.portable.json"
$portableVaelor = Join-Path $cfg "templates\vaelor.portable.json"
$portableModels = Join-Path $cfg "templates\models.portable.json"
if (Test-Path $portableAutonomy) { Copy-Item $portableAutonomy (Join-Path $cfg "autonomy.json") -Force }
if (Test-Path $portableVaelor) { Copy-Item $portableVaelor (Join-Path $cfg "vaelor.json") -Force }
if (Test-Path $portableModels) { Copy-Item $portableModels (Join-Path $cfg "models.json") -Force }
# network is per-machine; do not ship a bound port from the builder PC
if (Test-Path (Join-Path $cfg "network.json")) { Remove-Item (Join-Path $cfg "network.json") -Force }
if (Test-Path (Join-Path $cfg "setup_complete.json")) { Remove-Item (Join-Path $cfg "setup_complete.json") -Force }
# Remote API credentials are machine-local secrets and must never enter a release archive.
if (Test-Path (Join-Path $cfg "api_access.json")) { Remove-Item (Join-Path $cfg "api_access.json") -Force }
# docs that mention a specific Windows username
$sandboxDoc = Join-Path $cfg "SANDBOX_GOD_MODE.md"
if (Test-Path $sandboxDoc) {
  $txt = Get-Content $sandboxDoc -Raw
  $txt = $txt -replace 'C:\\Users\\[^\\\s]+', 'C:\Users\<you>'
  $txt = $txt -replace 'S:\\[^\s]+', '<install-folder>'
  Set-Content $sandboxDoc -Value $txt -Encoding UTF8
}

# Fresh empty memory skeleton for testers
$mem = Join-Path $payload "memory"
New-Item -ItemType Directory -Path $mem -Force | Out-Null
'[]' | Set-Content (Join-Path $mem "archive.json") -Encoding UTF8
'{}' | Set-Content (Join-Path $mem "conversations.json") -Encoding UTF8
"" | Set-Content (Join-Path $mem "audit_log.jsonl") -Encoding UTF8

# Bootstrap README for zip recipients
@"
# Vaelor Alpha $AlphaVersion

## Install (Windows)
1. Unzip this folder anywhere (or run the installer script).
2. Right-click ``installer\Install-Vaelor-Alpha.ps1`` → Run with PowerShell
   - Or from PowerShell:
     ``powershell -ExecutionPolicy Bypass -File installer\Install-Vaelor-Alpha.ps1``
3. Double-click **Vaelor Alpha** on your Desktop (or ``Start-Vaelor.bat``).
4. Open http://localhost:8000 and click the tome.

## Requirements
- Windows 10/11
- Python 3.10+ on PATH (https://www.python.org/downloads/)
- Optional: Ollama or LM Studio for local LLM

## Safety
Broad dev/install access. Hard blocks against deleting core OS files.
See ``config\SANDBOX_GOD_MODE.md`` and ``CODER_BRIEFING.md``.

## Name
Vaelor is pronounced **Vay-lore**.
"@ | Set-Content (Join-Path $payload "ALPHA_README.txt") -Encoding UTF8

# One-click install for zip users
@"
@echo off
cd /d "%~dp0"
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0installer\Install-Vaelor-Alpha.ps1" -SourceDir "%~dp0" -OpenWhenDone
pause
"@ | Set-Content (Join-Path $payload "INSTALL.bat") -Encoding ASCII

$zip = Join-Path $OutDir ("Vaelor-Alpha-{0}.zip" -f $AlphaVersion)
if (Test-Path $zip) { Remove-Item $zip -Force }

Write-Host "Compressing $zip ..."
Compress-Archive -Path $payload -DestinationPath $zip -Force

# Also write a simple SHA256 for integrity
$hash = (Get-FileHash -Algorithm SHA256 $zip).Hash
$hash | Set-Content ($zip + ".sha256") -Encoding ASCII

Remove-Item -LiteralPath $stage -Recurse -Force -ErrorAction SilentlyContinue

Write-Host ""
Write-Host "Built: $zip"
Write-Host "SHA256: $hash"
Write-Host "Size: $([math]::Round((Get-Item $zip).Length / 1MB, 2)) MB"
Write-Host ""
Write-Host "Give testers the zip + tell them to run INSTALL.bat (needs Python)."

