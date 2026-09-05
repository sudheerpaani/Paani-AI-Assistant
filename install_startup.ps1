param (
    [switch]$Uninstall
)

$ErrorActionPreference = 'Stop'
$appDir = $PSScriptRoot
if (-not $appDir) { $appDir = Get-Location }

$startupDir = [System.IO.Path]::Combine($env:APPDATA, 'Microsoft', 'Windows', 'Start Menu', 'Programs', 'Startup')
$shortcutPath = Join-Path $startupDir 'Paani 2.0.lnk'
$vbsPath = Join-Path $appDir 'launch.vbs'

if ($Uninstall) {
    if (Test-Path $shortcutPath) {
        Remove-Item -Path $shortcutPath -Force
        Write-Host "[UNINSTALL] Paani 2.0 auto-start shortcut removed from Windows Startup folder." -ForegroundColor Yellow
    } else {
        Write-Host "[UNINSTALL] Auto-start shortcut not found." -ForegroundColor Gray
    }
    exit 0
}

if (-not (Test-Path $vbsPath)) {
    Write-Host "[ERROR] launch.vbs not found at $vbsPath." -ForegroundColor Red
    exit 1
}

$WshShell = New-Object -ComObject WScript.Shell
$shortcut = $WshShell.CreateShortcut($shortcutPath)
$shortcut.TargetPath = "wscript.exe"
$shortcut.Arguments = "`"$vbsPath`""
$shortcut.WorkingDirectory = $appDir
$shortcut.Description = "Paani 2.0 Autonomous AI Assistant & System Tray Companion"
$shortcut.Save()

Write-Host "==================================================" -ForegroundColor Cyan
Write-Host "  PAANI 2.0 AUTO-START REGISTRATION COMPLETE" -ForegroundColor Cyan
Write-Host "==================================================" -ForegroundColor Cyan
Write-Host "Created Shortcut: $shortcutPath" -ForegroundColor Green
Write-Host "Target Launcher : $vbsPath" -ForegroundColor Green
Write-Host "Status          : Active (Will start silently on Windows boot)" -ForegroundColor Green
