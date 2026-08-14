param(
    [Parameter(Mandatory)]
    [ValidateSet(
        "opening",
        "evening",
        "late_night",
        "morning",
        "afternoon"
    )]
    [string]$SnapshotRole,

    [switch]$ValidateOnly,

    [switch]$DryRun
)

$ErrorActionPreference = "Stop"

if ($ValidateOnly -and $DryRun) {
    throw (
        "ValidateOnly and DryRun cannot be used together."
    )
}

$ProjectRoot = Split-Path -Parent $PSScriptRoot
$PythonPath = "D:\SportsModel\.venv\Scripts\python.exe"

$ResolverPath = Join-Path `
    $ProjectRoot `
    "scripts\resolve_moneyline_snapshot_target.py"

$SnapshotWrapperPath = Join-Path `
    $ProjectRoot `
    "scripts\run_moneyline_odds_snapshot.ps1"

$SourcePath = Join-Path $ProjectRoot "src"
$EnvironmentPath = "D:\SportsModel\.env"

$LogDirectory = Join-Path `
    $ProjectRoot `
    "logs\moneyline_odds_snapshot_tasks"

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
    "$($SnapshotRole)_snapshot_task_$Timestamp.log"

function Write-Log {
    param(
        [Parameter(Mandatory)]
        [string]$Message
    )

    $Line = (
        "[{0}] {1}" -f `
        (Get-Date -Format "yyyy-MM-dd HH:mm:ss"),
        $Message
    )

    Write-Host $Line

    Add-Content `
        -Path $LogPath `
        -Value $Line `
        -Encoding ASCII
}

try {
    foreach ($RequiredPath in @(
        $PythonPath,
        $ResolverPath,
        $SnapshotWrapperPath,
        $SourcePath,
        $EnvironmentPath
    )) {
        if (-not (Test-Path $RequiredPath)) {
            throw "Required path was not found: $RequiredPath"
        }
    }

    Set-Location $ProjectRoot

    $env:PYTHONPATH = $SourcePath
    $env:SPORTSMODEL_ENV_FILE = $EnvironmentPath
    $env:PYTHONUNBUFFERED = "1"

    $TargetDateOutput = & $PythonPath `
        $ResolverPath `
        --snapshot-role $SnapshotRole

    if ($LASTEXITCODE -ne 0) {
        throw (
            "Target-date resolver failed with exit code " +
            "$LASTEXITCODE."
        )
    }

    $TargetDate = (
        $TargetDateOutput |
            Select-Object -Last 1
    ).Trim()

    $ParsedDate = [datetime]::MinValue

    $ValidDate = [datetime]::TryParseExact(
        $TargetDate,
        "yyyy-MM-dd",
        [System.Globalization.CultureInfo]::InvariantCulture,
        [System.Globalization.DateTimeStyles]::None,
        [ref]$ParsedDate
    )

    if (-not $ValidDate) {
        throw (
            "Resolver returned an invalid target date: " +
            "$TargetDate"
        )
    }

    Write-Log "============================================================"
    Write-Log "Starting fixed Moneyline snapshot task"
    Write-Log "Project root: $ProjectRoot"
    Write-Log "Snapshot role: $SnapshotRole"
    Write-Log "Resolved target date: $TargetDate"
    Write-Log "============================================================"

    if ($ValidateOnly) {
        Write-Log "Validation-only mode enabled."

        & $SnapshotWrapperPath -ValidateOnly

        if ($LASTEXITCODE -ne 0) {
            throw (
                "Snapshot wrapper validation failed with " +
                "exit code $LASTEXITCODE."
            )
        }

        Write-Log "Task validation completed successfully."
        Write-Log "No database or live odds work was executed."
        Write-Log "Log file: $LogPath"
        return
    }

    if ($DryRun) {
        Write-Log "Dry-run mode enabled."
        Write-Log "Running snapshot schedule tests."

        & $PythonPath `
            -m pytest `
            tests\orchestration\test_odds_snapshot_schedule.py `
            -q

        if ($LASTEXITCODE -ne 0) {
            throw (
                "Snapshot schedule tests failed with " +
                "exit code $LASTEXITCODE."
            )
        }

        & $SnapshotWrapperPath -DryRun

        if ($LASTEXITCODE -ne 0) {
            throw (
                "Snapshot wrapper dry run failed with " +
                "exit code $LASTEXITCODE."
            )
        }

        Write-Log "Task dry run completed successfully."
        Write-Log "No database or live odds work was executed."
        Write-Log "Log file: $LogPath"
        return
    }

    Write-Log "Live task execution enabled."

    & $SnapshotWrapperPath `
        -SnapshotRole $SnapshotRole `
        -TargetDate $TargetDate

    if ($LASTEXITCODE -ne 0) {
        throw (
            "Snapshot execution failed with exit code " +
            "$LASTEXITCODE."
        )
    }

    Write-Log "Fixed snapshot task completed successfully."
    Write-Log "Log file: $LogPath"
}
catch {
    Write-Log "ERROR: $($_.Exception.Message)"
    Write-Log "Log file: $LogPath"
    throw
}
