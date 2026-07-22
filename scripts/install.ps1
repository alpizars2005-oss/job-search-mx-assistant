$ErrorActionPreference = "Stop"
Set-Location (Split-Path $PSScriptRoot -Parent)

if (-not (Test-Path ".venv")) {
    py -m venv .venv
}

& .\.venv\Scripts\python.exe -m pip install -e .
& .\.venv\Scripts\python.exe -m jobsearch_assistant init --language es
Write-Host "Installation complete. Run scripts\run-gui.ps1"
