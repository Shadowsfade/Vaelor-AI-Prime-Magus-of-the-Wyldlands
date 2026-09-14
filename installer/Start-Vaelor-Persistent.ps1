# Start Vaelor through a per-user Scheduled Task so it survives the launching console/SSH session.
param(
  [Parameter(Mandatory=$true)][string]$Root,
  [Parameter(Mandatory=$true)][string]$BindHost,
  [Parameter(Mandatory=$true)][ValidateRange(1024,65535)][int]$Port
)
$ErrorActionPreference = "Stop"
$Root = (Resolve-Path $Root).Path.TrimEnd("\")
$python = Join-Path $Root ".venv\Scripts\python.exe"
$runner = Join-Path $Root "installer\run_api.bat"
$taskName = "Vaelor-API"
if (-not (Test-Path $python)) { throw "Missing Vaelor runtime: $python" }
if (-not (Test-Path $runner)) { throw "Missing Vaelor API runner: $runner" }
$action = New-ScheduledTaskAction -Execute $env:ComSpec -Argument ('/d /c ""{0}" "{1}" "{2}""' -f $runner, $BindHost, $Port) -WorkingDirectory $Root
$trigger = New-ScheduledTaskTrigger -AtLogOn -User $env:USERNAME
$principal = New-ScheduledTaskPrincipal -UserId $env:USERNAME -LogonType Interactive -RunLevel Limited
$settings = New-ScheduledTaskSettingsSet -MultipleInstances IgnoreNew -ExecutionTimeLimit ([TimeSpan]::Zero)
Register-ScheduledTask -TaskName $taskName -Action $action -Trigger $trigger -Principal $principal -Settings $settings -Force | Out-Null
Start-ScheduledTask -TaskName $taskName
$deadline = (Get-Date).AddSeconds(15)
do {
  Start-Sleep -Milliseconds 250
  $listening = Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue
} until ($listening -or (Get-Date) -ge $deadline)
if (-not $listening) { throw "Vaelor task was registered but did not listen on port $Port. See $env:TEMP\vaelor-api.log" }
Write-Output ("Vaelor task {0} is running on {1}:{2}" -f $taskName, $BindHost, $Port)
