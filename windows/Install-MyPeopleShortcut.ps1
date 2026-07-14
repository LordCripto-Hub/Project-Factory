$ErrorActionPreference = 'Stop'
$launcher = Join-Path $PSScriptRoot 'Start-MyPeople.ps1'
if (-not (Test-Path -LiteralPath $launcher)) { throw "Launcher missing: $launcher" }

$desktop = [Environment]::GetFolderPath('Desktop')
$shortcutPath = Join-Path $desktop 'MyPeople.lnk'
$shell = New-Object -ComObject WScript.Shell
$shortcut = $shell.CreateShortcut($shortcutPath)
$shortcut.TargetPath = "$env:SystemRoot\System32\WindowsPowerShell\v1.0\powershell.exe"
$shortcut.Arguments = "-NoProfile -ExecutionPolicy Bypass -WindowStyle Hidden -File `"$launcher`""
$shortcut.WorkingDirectory = Split-Path -Parent $launcher
$shortcut.Description = 'Start MyPeople in Docker and open Priorities'
$dockerDesktop = 'C:\Program Files\Docker\Docker\Docker Desktop.exe'
$shortcut.IconLocation = if (Test-Path -LiteralPath $dockerDesktop) { "$dockerDesktop,0" } else { "$env:SystemRoot\System32\shell32.dll,25" }
$shortcut.Save()

Write-Host "MyPeople shortcut installed: $shortcutPath"
