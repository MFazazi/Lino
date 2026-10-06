$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $MyInvocation.MyCommand.Path
$Core = Join-Path $Root "core"
$Venv = Join-Path $Core ".venv"
$Python = Join-Path $Venv "Scripts\python.exe"
$Requirements = Join-Path $Core "requirements.txt"
$RequirementsMarker = Join-Path $Venv ".lino-requirements"

Write-Host "Lino v0.2.4" -ForegroundColor Cyan

if (-not (Test-Path $Python)) {
    Write-Host "Preparation du moteur Lino..." -ForegroundColor DarkCyan
    python -m venv $Venv
    & $Python -m pip install --upgrade pip
}

# Installe uniquement si requirements.txt a changé depuis le dernier lancement.
$RequirementsHash = (Get-FileHash $Requirements -Algorithm SHA256).Hash
$InstalledHash = if (Test-Path $RequirementsMarker) { (Get-Content $RequirementsMarker -Raw).Trim() } else { "" }
if ($InstalledHash -ne $RequirementsHash) {
    Write-Host "Mise a jour des composants Lino..." -ForegroundColor DarkCyan
    & $Python -m pip install -r $Requirements
    Set-Content -Path $RequirementsMarker -Value $RequirementsHash -NoNewline
}

if (-not (Test-Path (Join-Path $Root "node_modules"))) {
    Write-Host "Preparation de l'interface..." -ForegroundColor DarkCyan
    Set-Location $Root
    npm install
}

Set-Location $Root
Write-Host "Demarrage de Lino..." -ForegroundColor Green
npm run tauri dev
