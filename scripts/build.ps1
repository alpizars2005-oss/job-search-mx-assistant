$ErrorActionPreference = "Stop"
Set-Location (Split-Path $PSScriptRoot -Parent)
& .\.venv\Scripts\python.exe -m pip install -e ".[build]"
& .\.venv\Scripts\python.exe -m PyInstaller --noconfirm --clean --onefile --windowed --paths src --name JobSearchAssistant run_gui.py
Write-Host "Build complete: dist\JobSearchAssistant.exe"
