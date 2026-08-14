[CmdletBinding()]
param(
    [ValidateRange(1, 65535)]
    [int]$Port = 8501
)

$ErrorActionPreference = "Stop"

$repositoryRoot = Split-Path `
    -Parent `
    $PSScriptRoot

$sourcePath = Join-Path `
    $repositoryRoot `
    "src"

$appPath = Join-Path `
    $sourcePath `
    "sportsmodel\dashboard\app.py"

$env:PYTHONPATH = $sourcePath

$pythonCandidates = @(
    (
        Join-Path `
            $repositoryRoot `
            ".venv\Scripts\python.exe"
    ),
    "D:\SportsModel\.venv\Scripts\python.exe"
)

$pythonPath = $pythonCandidates |
    Where-Object {
        Test-Path $_
    } |
    Select-Object -First 1

if (-not $pythonPath) {
    $pythonCommand = Get-Command `
        python `
        -ErrorAction SilentlyContinue

    if (-not $pythonCommand) {
        throw (
            "Unable to locate a Python interpreter. " +
            "Create a virtual environment or install Python."
        )
    }

    $pythonPath = $pythonCommand.Source
}

Write-Host "SportsModel dashboard"
Write-Host "Repository: $repositoryRoot"
Write-Host "Python:     $pythonPath"
Write-Host "Address:    http://127.0.0.1:$Port"

& $pythonPath `
    -m streamlit run `
    $appPath `
    "--server.address=127.0.0.1" `
    "--server.port=$Port" `
    "--server.headless=true"

exit $LASTEXITCODE
