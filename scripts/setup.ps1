# One-time local setup: creates a venv and installs backend deps.
$ErrorActionPreference = "Stop"
Set-Location (Join-Path $PSScriptRoot "..")

python -m venv .venv
& .\.venv\Scripts\Activate.ps1
pip install --upgrade pip
pip install -r backend/requirements.txt

Push-Location frontend
npm install
npm run build
Pop-Location

Write-Host ""
Write-Host "Setup done. Activate with: .\.venv\Scripts\Activate.ps1"
Write-Host "Run the server with:      python backend/app.py"
Write-Host "Rebuild CSS during frontend dev with: cd frontend; npm run watch"
