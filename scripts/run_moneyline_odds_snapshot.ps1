param(
    [ValidateSet(
        "opening",
        "evening",
        "late_night",
        "morning",
        "afternoon",
        "near_close"
    )]
    [string]$SnapshotRole,

    [string]$TargetDate,

    [switch]$ValidateOnly,

    [switch]$DryRun
)

$ErrorActionPreference = "Stop"

$ProjectRoot = Split-Path -Parent $PSScriptRoot
$PythonPath = "D:\SportsModel\.venv\Scripts\python.exe"
$ScriptPath = Join-Path `
    $ProjectRoot `
    "scripts\fetch_mlb_odds.py"
$SourcePath = Join-Path $ProjectRoot "src"
$EnvironmentPath = "D:\SportsModel\.env"
$DatabaseReadinessPath = Join-Path `
    $ProjectRoot `
    "scripts\wait_for_sportsmodel_database.ps1"
$LogDirectory = Join-Path `
    $ProjectRoot `
    "logs\moneyline_odds_snapshots"

if (-not (Test-Path $LogDirectory)) {
    New-Item `
        -ItemType Directory `
        -Path $LogDirectory `
        -Force |
        Out-Null
}

$Timestamp = Get-Date -Format "yyyy-MM-dd_HH-mm-ss"
$LogPath = Join-Path `
    $LogDirectory `
    "moneyline_odds_snapshot_$Timestamp.log"

function Write-Log {
    param(
        [Parameter(Mandatory)]
        [string]$Message
    )

    $LogTimestamp = Get-Date -Format "yyyy-MM-dd HH:mm:ss"
    $FormattedMessage = "[$LogTimestamp] $Message"

    Write-Host $FormattedMessage
    Add-Content `
        -Path $LogPath `
        -Value $FormattedMessage
}

try {
    if ($ValidateOnly -and $DryRun) {
        throw "Choose either -ValidateOnly or -DryRun, not both."
    }

    $LiveExecution = (-not $ValidateOnly) -and (-not $DryRun)

    $NormalizedTargetDate = $null

    if ($LiveExecution) {
        if ([string]::IsNullOrWhiteSpace($SnapshotRole)) {
            throw (
                "SnapshotRole is required for live execution. " +
                "Choose opening, evening, late_night, morning, " +
                "afternoon, or near_close."
            )
        }

        if ([string]::IsNullOrWhiteSpace($TargetDate)) {
            throw (
                "TargetDate is required for live execution. " +
                "Use YYYY-MM-DD format."
            )
        }

        $ParsedTargetDate = [datetime]::MinValue

        $ValidTargetDate = [datetime]::TryParseExact(
            $TargetDate,
            "yyyy-MM-dd",
            [System.Globalization.CultureInfo]::InvariantCulture,
            [System.Globalization.DateTimeStyles]::None,
            [ref]$ParsedTargetDate
        )

        if (-not $ValidTargetDate) {
            throw "TargetDate must use YYYY-MM-DD format."
        }

        $NormalizedTargetDate = (
            $ParsedTargetDate.ToString("yyyy-MM-dd")
        )
    }

    Write-Log "============================================================"
    Write-Log "Starting SportsModel Moneyline odds snapshot wrapper"
    Write-Log "Project root: $ProjectRoot"
    Write-Log "Python executable: $PythonPath"
    Write-Log "Python script: $ScriptPath"
    Write-Log "Python source path: $SourcePath"
    Write-Log "Environment file: $EnvironmentPath"
    Write-Log "============================================================"

    if (-not (Test-Path $PythonPath)) {
        throw "Python executable was not found: $PythonPath"
    }

    if (-not (Test-Path $ScriptPath)) {
        throw "Odds snapshot script was not found: $ScriptPath"
    }

    if (-not (Test-Path $SourcePath)) {
        throw "SportsModel source directory was not found: $SourcePath"
    }

    if (-not (Test-Path $EnvironmentPath)) {
        throw "SportsModel environment file was not found: $EnvironmentPath"
    }

    if (-not (Test-Path $DatabaseReadinessPath)) {
        throw "Database readiness helper was not found: $DatabaseReadinessPath"
    }

    Set-Location $ProjectRoot

    $env:SPORTSMODEL_ENV_FILE = $EnvironmentPath
    $env:PYTHONPATH = $SourcePath
    $env:PYTHONUNBUFFERED = "1"

    if ($ValidateOnly) {
        Write-Log "Validation-only mode enabled."

        $ResolvedModulePath = & $PythonPath -c `
            "import sportsmodel.ingest.odds_cli as module; print(module.__file__)"

        if ($LASTEXITCODE -ne 0) {
            throw (
                "Python module validation exited with code " +
                "$LASTEXITCODE."
            )
        }

        $ResolvedModulePath = (
            $ResolvedModulePath |
            Select-Object -Last 1
        ).ToString().Trim()

        Write-Log "Resolved odds CLI module: $ResolvedModulePath"

        if (-not $ResolvedModulePath.StartsWith(
            $SourcePath,
            [System.StringComparison]::OrdinalIgnoreCase
        )) {
            throw (
                "SportsModel resolved outside this worktree: " +
                $ResolvedModulePath
            )
        }

        & $PythonPath $ScriptPath --help 2>&1 |
            ForEach-Object {
                $Line = $_.ToString()
                Write-Host $Line
                Add-Content `
                    -Path $LogPath `
                    -Value $Line
            }

        $PythonExitCode = $LASTEXITCODE

        if ($PythonExitCode -ne 0) {
            throw (
                "Odds snapshot CLI validation exited with code " +
                "$PythonExitCode."
            )
        }

        Write-Log "Validation completed successfully."
        Write-Log "No database or live odds work was executed."
        Write-Log "Log file: $LogPath"

        exit 0
    }

    if ($DryRun) {
        Write-Log "Dry-run mode enabled."
        Write-Log "Running focused snapshot and orchestration tests."
        Write-Log "No database or live odds work will be executed."

        & $PythonPath -m pytest `
            tests\database\test_connection.py `
            tests\ingest\test_odds_api.py `
            tests\ingest\test_odds_cli.py `
            tests\orchestration\test_moneyline_daily.py `
            tests\orchestration\test_moneyline_daily_cli.py `
            -q 2>&1 |
            ForEach-Object {
                $Line = $_.ToString()
                Write-Host $Line
                Add-Content `
                    -Path $LogPath `
                    -Value $Line
            }

        $PythonExitCode = $LASTEXITCODE

        if ($PythonExitCode -ne 0) {
            throw (
                "Odds snapshot dry run exited with code " +
                "$PythonExitCode."
            )
        }

        Write-Log "Odds snapshot dry run completed successfully."
        Write-Log "No database or live odds work was executed."
        Write-Log "Log file: $LogPath"

        exit 0
    }

    Write-Log "Live snapshot execution enabled."
    Write-Log "Snapshot role: $SnapshotRole"
    Write-Log "Target date: $NormalizedTargetDate"

    . $DatabaseReadinessPath

    Write-Log "Checking SportsModel database readiness."

    $DatabaseLogger = {
        param([string]$Message)
        Write-Log $Message
    }

    Wait-SportsModelDatabaseReady `
        -PythonPath $PythonPath `
        -SourcePath $SourcePath `
        -TimeoutSeconds 600 `
        -PollSeconds 15 `
        -Logger $DatabaseLogger

    Write-Log "Database readiness check completed."

    & $PythonPath `
        $ScriptPath `
        --snapshot-role $SnapshotRole `
        --target-date $NormalizedTargetDate 2>&1 |
        ForEach-Object {
            $Line = $_.ToString()
            Write-Host $Line
            Add-Content `
                -Path $LogPath `
                -Value $Line
        }

    $PythonExitCode = $LASTEXITCODE

    if ($PythonExitCode -ne 0) {
        throw (
            "Odds snapshot ingestion exited with code " +
            "$PythonExitCode."
        )
    }

    Write-Log "Moneyline odds snapshot completed successfully."
    Write-Log "Log file: $LogPath"

    exit 0
}
catch {
    Write-Log "ERROR: $($_.Exception.Message)"
    Write-Log "Moneyline odds snapshot wrapper failed."
    Write-Log "Log file: $LogPath"

    exit 1
}
