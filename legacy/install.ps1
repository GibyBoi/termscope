# TermScope installer.
# Run:  powershell -ExecutionPolicy Bypass -File install.ps1
#   or just double-click "Install TermScope.bat".
$ErrorActionPreference = "Stop"
$proj = Split-Path -Parent $MyInvocation.MyCommand.Definition

Write-Host ""
Write-Host "============================================" -ForegroundColor Cyan
Write-Host "  Installing TermScope" -ForegroundColor Cyan
Write-Host "============================================" -ForegroundColor Cyan
Write-Host "  Folder: $proj"

# --- Python ---------------------------------------------------------------
$py = (Get-Command python -ErrorAction SilentlyContinue).Source
if (-not $py) {
    Write-Host "ERROR: Python 3 was not found on your PATH." -ForegroundColor Red
    Write-Host "Install Python 3.10+ (python.org or the Microsoft Store), then re-run this." -ForegroundColor Red
    exit 1
}
Write-Host "  Python: $py"

# --- 1/4 dependencies -----------------------------------------------------
Write-Host ""
Write-Host "[1/4] Installing Python dependencies..." -ForegroundColor Cyan
& $py -m pip install --user -r (Join-Path $proj "requirements.txt")
if ($LASTEXITCODE -ne 0) { Write-Host "ERROR: dependency install failed." -ForegroundColor Red; exit 1 }

# --- 2/4 speech model -----------------------------------------------------
Write-Host ""
Write-Host "[2/4] Checking the offline speech model..." -ForegroundColor Cyan
& $py (Join-Path $proj "run.py") download-model

# --- 3/4 jargon library ---------------------------------------------------
Write-Host ""
$lib = Join-Path $proj "data\library.json"
if (Test-Path $lib) {
    Write-Host "[3/4] Jargon library already present - skipping." -ForegroundColor Cyan
} else {
    Write-Host "[3/4] Building the jargon library from online dictionaries (one-time)..." -ForegroundColor Cyan
    & $py (Join-Path $proj "run.py") enrich-library
}

# --- 4/4 shortcuts + taskbar identity ------------------------------------
Write-Host ""
Write-Host "[4/4] Creating Start-menu and Desktop shortcuts..." -ForegroundColor Cyan
& powershell -ExecutionPolicy Bypass -File (Join-Path $proj "scripts\create_shortcuts.ps1")

Write-Host ""
Write-Host "============================================" -ForegroundColor Green
Write-Host "  TermScope installed." -ForegroundColor Green
Write-Host "============================================" -ForegroundColor Green
Write-Host "  Launch it from the Start menu or the Desktop shortcut."
Write-Host "  To pin: right-click its taskbar button and choose 'Pin to taskbar'."
Write-Host ""
