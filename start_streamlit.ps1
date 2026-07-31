$ErrorActionPreference = "Stop"

$ProjectRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$Python = Join-Path $ProjectRoot ".venv-codex\Scripts\python.exe"

if (-not (Test-Path $Python)) {
    Write-Host "Creating local Python environment..."
    python -m venv (Join-Path $ProjectRoot ".venv-codex")
}

if (-not (Test-Path $Python)) {
    throw "Could not find .venv-codex Python. Install Python, then run this script again."
}

Write-Host "Installing dependencies..."
& $Python -m pip install -r (Join-Path $ProjectRoot "requirements.txt")

Write-Host ""
Write-Host "Starting AgentForge Streamlit Dashboard at http://localhost:8501"
Write-Host "Press Ctrl+C to stop."
Set-Location $ProjectRoot
& $Python -m streamlit run app.py
