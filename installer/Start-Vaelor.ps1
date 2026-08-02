$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $PSScriptRoot
if (-not (Test-Path (Join-Path $Root "api\server.py"))) { $Root = $PSScriptRoot }
Set-Location $Root
$py = Join-Path $Root ".venv\Scripts\python.exe"
if (-not (Test-Path $py)) { Write-Host "Missing .venv. Run installer\Install-Vaelor-Alpha.ps1 first."; exit 1 }
Write-Host "Starting Vaelor at http://localhost:8000 ..."
Start-Process "http://localhost:8000"
& $py -m uvicorn api.server:app --host localhost --port 8000
