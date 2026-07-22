$ErrorActionPreference = "Stop"
Set-Location (Split-Path $PSScriptRoot -Parent)
if (Test-Path ".venv\Scripts\python.exe") {
    & .\.venv\Scripts\python.exe -m jobsearch_assistant @args
} else {
    $env:PYTHONPATH = (Join-Path (Get-Location) "src")
    py -m jobsearch_assistant @args
}
