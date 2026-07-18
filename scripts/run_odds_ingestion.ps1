$ErrorActionPreference = "Stop"

$ProjectRoot = "D:\SportsModel"
$PythonPath = Join-Path $ProjectRoot ".venv\Scripts\python.exe"
$ScriptPath = Join-Path $ProjectRoot "scripts\fetch_mlb_odds.py"
$LogDirectory = Join-Path $ProjectRoot "logs\odds"

if (-not (Test-Path $LogDirectory)) {
    New-Item `
        -ItemType Directory `
        -Path $LogDirectory `
        -Force |
        Out-Null
}

$Timestamp = Get-Date -Format "yyyy-MM-dd_HH-mm-ss"
$LogPath = Join-Path $LogDirectory "odds_ingestion_$Timestamp.log"

function Write-Log {
    param(
        [Parameter(Mandatory)]
        [string]$Message
    )

    $LogTimestamp = Get-Date -Format "yyyy-MM-dd HH:mm:ss"
    $FormattedMessage = "[$LogTimestamp] $Message"

    Write-Host $FormattedMessage
    Add-Content -Path $LogPath -Value $FormattedMessage
}

try {
    Write-Log "============================================================"
    Write-Log "Starting SportsModel odds ingestion"
    Write-Log "Project root: $ProjectRoot"
    Write-Log "Python executable: $PythonPath"
    Write-Log "Python script: $ScriptPath"
    Write-Log "============================================================"

    if (-not (Test-Path $PythonPath)) {
        throw "Python executable was not found: $PythonPath"
    }

    if (-not (Test-Path $ScriptPath)) {
        throw "Odds ingestion script was not found: $ScriptPath"
    }

    Set-Location $ProjectRoot

    & $PythonPath $ScriptPath 2>&1 |
        ForEach-Object {
            $Line = $_.ToString()
            Write-Host $Line
            Add-Content -Path $LogPath -Value $Line
        }

    $PythonExitCode = $LASTEXITCODE

    if ($PythonExitCode -ne 0) {
        throw "Odds ingestion exited with code $PythonExitCode."
    }

    Write-Log "Odds ingestion completed successfully."
    Write-Log "Log file: $LogPath"

    exit 0
}
catch {
    Write-Log "ERROR: $($_.Exception.Message)"
    Write-Log "Odds ingestion failed."
    Write-Log "Log file: $LogPath"

    exit 1
}
