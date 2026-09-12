# Install the complete frozen desktop folder for the current user.
param([string]$InstallDir = (Join-Path $env:LOCALAPPDATA 'Programs\Vaelor'))
$ErrorActionPreference = 'Stop'
$source = [IO.Path]::GetFullPath($PSScriptRoot)
$target = [IO.Path]::GetFullPath($InstallDir)
if ($target -eq $source -or $target.StartsWith($source + [IO.Path]::DirectorySeparatorChar, [StringComparison]::OrdinalIgnoreCase)) {
    throw 'Choose an installation directory outside the extracted package.'
}
if (Test-Path -LiteralPath $target) { throw 'Destination exists. Choose a new folder to preserve existing data.' }
if (-not (Test-Path -LiteralPath (Join-Path $source 'Vaelor.exe'))) { throw 'Run this script from the extracted desktop package.' }
New-Item -ItemType Directory -Path $target | Out-Null
Get-ChildItem -LiteralPath $source -Force | Copy-Item -Destination $target -Recurse
$shortcut = (New-Object -ComObject WScript.Shell).CreateShortcut((Join-Path ([Environment]::GetFolderPath('Desktop')) 'Vaelor.lnk'))
$shortcut.TargetPath = Join-Path $target 'Vaelor.exe'
$shortcut.WorkingDirectory = $target
$shortcut.Save()
Write-Host "Installed Vaelor to $target. Python is bundled; model backend and WebView2 remain separate."
