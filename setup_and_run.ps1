# Paani 2.0 Master Bootstrap & Setup Script
# Excludes ./paani_profile/ from cleanup, initializes Python venv, installs Playwright & Ollama, launches Gateway server, and opens HUD UI

$ErrorActionPreference = 'Continue'
$appDir = $PSScriptRoot
if (-not $appDir) { $appDir = Get-Location }

Set-Location $appDir

Write-Host "==================================================" -ForegroundColor Cyan
Write-Host "  PAANI 2.0 - OLLAMA COGNITIVE BRAIN & SQLITE ENGINE" -ForegroundColor Cyan
Write-Host "==================================================" -ForegroundColor Cyan

# 1. Eradicate legacy build artifacts (Excluding ./paani_profile/ persistent browser state)
Write-Host "[1/5] Checking workspace cleanliness (preserving ./paani_profile/)..." -ForegroundColor Yellow
$purgeFolders = @('node_modules', 'dist', 'build', '.cache', 'src', 'tests', 'planning')
foreach ($folder in $purgeFolders) {
    $targetPath = Join-Path $appDir $folder
    if (Test-Path $targetPath) {
        Write-Host "      Purging $folder..." -ForegroundColor Gray
        Remove-Item -Path $targetPath -Recurse -Force -ErrorAction SilentlyContinue
    }
}

# Ensure persistent Chromium profile directory exists
$profileDir = Join-Path $appDir "paani_profile"
if (-not (Test-Path $profileDir)) {
    New-Item -ItemType Directory -Path $profileDir -Force | Out-Null
    Write-Host "      Created persistent browser profile folder at $profileDir" -ForegroundColor Green
} else {
    Write-Host "      Persistent browser profile folder active at $profileDir" -ForegroundColor Green
}

# 2. Setup & Permission Check for Python Virtual Environment
$venvDir = Join-Path $appDir "paani_env"
Write-Host "[2/5] Verifying Python Environment and Venv Permissions ($venvDir)..." -ForegroundColor Yellow

$pythonCmd = "python"
if (-not (Test-Path $venvDir)) {
    try {
        & python -m venv $venvDir
        Write-Host "      Virtual environment 'paani_env' created successfully." -ForegroundColor Green
    } catch {
        Write-Host "      Venv creation warning: $($_.Exception.Message). Falling back to global Python runtime." -ForegroundColor Yellow
    }
}

$venvPython = Join-Path $venvDir "Scripts\python.exe"
if (Test-Path $venvPython) {
    $pythonCmd = $venvPython
    Write-Host "      Using isolated virtual environment: $venvPython" -ForegroundColor Green
} else {
    Write-Host "      Using system Python environment." -ForegroundColor Gray
}

# 3. Install Playwright & Ollama Dependencies
Write-Host "[3/5] Checking Playwright and Ollama cognitive dependencies..." -ForegroundColor Yellow
try {
    & $pythonCmd -m pip install --upgrade pip --quiet
    & $pythonCmd -m pip install playwright ollama edge-tts reportlab psutil pillow pystray pywebview keyboard requests apscheduler winotify numpy --quiet --no-warn-script-location
    & $pythonCmd -m playwright install chromium
    Write-Host "      Playwright Chromium browser and Ollama Python client ready." -ForegroundColor Green
} catch {
    Write-Host "      Dependencies setup notification: $($_.Exception.Message)" -ForegroundColor Yellow
}

# 4. Launch Gateway Server & Open HUD UI
Write-Host "[4/5] Starting Paani 2.0 Local Gateway Server at http://localhost:9120..." -ForegroundColor Cyan

# Terminate any existing python server running on port 9120
$existingPort = Get-NetTCPConnection -LocalPort 9120 -ErrorAction SilentlyContinue
if ($existingPort) {
    Stop-Process -Id $existingPort.OwningProcess -Force -ErrorAction SilentlyContinue
    Start-Sleep -Milliseconds 500
}

$serverProcess = Start-Process -FilePath $pythonCmd -ArgumentList "server.py" -WorkingDirectory $appDir -PassThru
Write-Host "      Gateway process started successfully." -ForegroundColor Green

Start-Sleep -Seconds 2

# 5. Launch Browser UI
Write-Host "==================================================" -ForegroundColor Cyan
Write-Host "  PAANI 2.0 IS LIVE AND RUNNING!" -ForegroundColor Cyan
Write-Host "  URL: http://localhost:9120" -ForegroundColor Green
Write-Host "==================================================" -ForegroundColor Cyan

Start-Process 'http://localhost:9120'
