$VaelorPath = $PSScriptRoot
$VenvActivate = "$VaelorPath\.venv\Scripts\Activate.ps1"

function Show-Menu {
    Clear-Host
    Write-Host "=========================================="
    Write-Host "           VAELOR LAUNCHER"
    Write-Host "=========================================="
    Write-Host "1) Start Vaelor (chat in this window)"
    Write-Host "2) Start Web Dashboard (browser)"
    Write-Host "3) Check status / diagnose problems"
    Write-Host "4) Exit"
    Write-Host "=========================================="
}

function Activate-Venv {
    if (Test-Path $VenvActivate) {
        & $VenvActivate
        return $true
    } else {
        Write-Host "PROBLEM: Virtual environment not found at:" -ForegroundColor Red
        Write-Host $VenvActivate
        Write-Host "Fix: this needs to be rebuilt. Ask Claude to help rebuild the venv."
        return $false
    }
}

function Start-VaelorCLI {
    Set-Location $VaelorPath
    if (Activate-Venv) {
        Write-Host ""
        Write-Host "Starting Vaelor..." -ForegroundColor Cyan
        Write-Host ""
        python vaelor.py
    }
    Read-Host "`nPress Enter to return to the menu"
}

function Start-WebDashboard {
    Set-Location $VaelorPath
    if (Activate-Venv) {
        Write-Host ""
        Write-Host "Starting Web Dashboard..." -ForegroundColor Cyan
        Write-Host "Once it says 'Application startup complete', open your browser to:"
        Write-Host "  http://localhost:8000" -ForegroundColor Yellow
        Write-Host ""
        Write-Host "Press CTRL+C in this window to stop the server."
        Write-Host ""
        python -m uvicorn api.server:app --host localhost --port 8000
    }
    Read-Host "`nPress Enter to return to the menu"
}

function Check-Status {
    Write-Host ""
    Write-Host "Checking Vaelor systems..." -ForegroundColor Cyan
    Write-Host ""

    if (Test-Path $VaelorPath) {
        Write-Host "[OK] Project folder found" -ForegroundColor Green
    } else {
        Write-Host "[PROBLEM] Project folder not found at $VaelorPath" -ForegroundColor Red
    }

    if (Test-Path $VenvActivate) {
        Write-Host "[OK] Virtual environment found" -ForegroundColor Green
    } else {
        Write-Host "[PROBLEM] Virtual environment missing" -ForegroundColor Red
    }

    $ollama = Get-Process -Name "ollama" -ErrorAction SilentlyContinue
    if ($ollama) {
        Write-Host "[OK] Ollama is running" -ForegroundColor Green
    } else {
        Write-Host "[PROBLEM] Ollama does not appear to be running" -ForegroundColor Red
        Write-Host "  Fix: open Ollama app, or run 'ollama serve' in a terminal"
    }

    $tailscale = Get-Service -Name "Tailscale" -ErrorAction SilentlyContinue
    if ($tailscale -and $tailscale.Status -eq "Running") {
        Write-Host "[OK] Tailscale service is running" -ForegroundColor Green
    } else {
        Write-Host "[PROBLEM] Tailscale service is not running" -ForegroundColor Red
    }

    $sshd = Get-Service -Name "sshd" -ErrorAction SilentlyContinue
    if ($sshd -and $sshd.Status -eq "Running") {
        Write-Host "[OK] SSH server is running (Legion Go can connect)" -ForegroundColor Green
    } else {
        Write-Host "[PROBLEM] SSH server is not running" -ForegroundColor Red
        Write-Host "  Fix (as Administrator): Start-Service sshd"
    }

    Write-Host ""
    Read-Host "Press Enter to return to the menu"
}

while ($true) {
    Show-Menu
    $choice = Read-Host "Choose an option"

    switch ($choice) {
        "1" { Start-VaelorCLI }
        "2" { Start-WebDashboard }
        "3" { Check-Status }
        "4" { exit }
        default { Write-Host "Invalid option" -ForegroundColor Yellow; Start-Sleep -Seconds 1 }
    }
}
