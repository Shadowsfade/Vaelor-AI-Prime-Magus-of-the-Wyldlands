#Requires -Version 5.1
param([string]$SourceDir = "", [string]$Python = "", [string]$OutDir = "")
$ErrorActionPreference = "Stop"
if (-not $SourceDir) { $SourceDir = Split-Path -Parent $PSScriptRoot }
$SourceDir = (Resolve-Path -LiteralPath $SourceDir).Path
if (-not $Python) { $Python = Join-Path $SourceDir '.venv\Scripts\python.exe' }
if (-not $OutDir) { $OutDir = Join-Path $SourceDir 'dist\desktop-1.1.4-alpha' }
if (-not (Test-Path -LiteralPath $Python)) { throw 'Supply -Python with a build environment containing requirements and PyInstaller.' }
& $Python (Join-Path $SourceDir 'installer\build_desktop.py') --source $SourceDir --output $OutDir
if ($LASTEXITCODE -ne 0) { throw 'Desktop build failed.' }
