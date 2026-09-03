param(
    [switch]$ValidateOnly,
    [switch]$DryRun
)

$ErrorActionPreference = "Stop"

$ProjectRoot = "D:\SportsModel"
$PythonPath = Join-Path $ProjectRoot ".venv\Scripts\python.exe"
$ScriptPath = Join-Path $ProjectRoot "scripts\run_moneyline_daily_pregame.py"
$SourcePath = Join-Path $ProjectRoot "src"
$DatabaseReadinessPath = Join-Path $ProjectRoot "scripts\wait_for_sportsmodel_database.ps1"
$ScheduledExecutionGuardPath = Join-Path $ProjectRoot "scripts\assert_moneyline_scheduled_execution.ps1"
$RetryHelperPath = Join-Path $ProjectRoot "scripts\invoke_moneyline_retry.ps1"
$LogDirectory = Join-Path $ProjectRoot "logs\moneyline_daily_pregame"

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
    "moneyline_daily_pregame_$Timestamp.log"

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
    Write-Log "Starting SportsModel daily Moneyline pregame workflow"
    Write-Log "Project root: $ProjectRoot"
    Write-Log "Python executable: $PythonPath"
    Write-Log "Python script: $ScriptPath"
    Write-Log "Python source path: $SourcePath"
    Write-Log "============================================================"

    if (-not (Test-Path $PythonPath)) {
        throw "Python executable was not found: $PythonPath"
    }

    if (-not (Test-Path $ScriptPath)) {
        throw "Daily pregame script was not found: $ScriptPath"
    }

    if (-not (Test-Path $SourcePath)) {
        throw "SportsModel source directory was not found: $SourcePath"
    }

    if (-not (Test-Path $DatabaseReadinessPath)) {
        throw "Database readiness helper was not found: $DatabaseReadinessPath"
    }

    if (-not (Test-Path $ScheduledExecutionGuardPath)) {
        throw (
            "Scheduled execution guard was not found: " +
            $ScheduledExecutionGuardPath
        )
    }

    if (-not (Test-Path $RetryHelperPath)) {
        throw "Moneyline retry helper was not found: $RetryHelperPath"
    }

    Set-Location $ProjectRoot

    $env:PYTHONPATH = $SourcePath
    $env:PYTHONUNBUFFERED = "1"

    if ($ValidateOnly) {
        Write-Log "Validation-only mode enabled."

        $ResolvedModulePath = & $PythonPath -c `
            "import sportsmodel.orchestration.moneyline_daily as module; print(module.__file__)"

        if ($LASTEXITCODE -ne 0) {
            throw "Python module validation exited with code $LASTEXITCODE."
        }

        $ResolvedModulePath = (
            $ResolvedModulePath |
            Select-Object -Last 1
        ).ToString().Trim()

        Write-Log "Resolved orchestration module: $ResolvedModulePath"

        if (-not $ResolvedModulePath.StartsWith(
            $SourcePath,
            [System.StringComparison]::OrdinalIgnoreCase
        )) {
            throw (
                "SportsModel resolved outside the core source tree: " +
                $ResolvedModulePath
            )
        }

        Write-Log "Validation completed successfully."
        Write-Log "No live pregame pipeline work was executed."
        Write-Log "Log file: $LogPath"

        exit 0
    }

    if ($ValidateOnly -and $DryRun) {
        throw "Choose either -ValidateOnly or -DryRun, not both."
    }

    if ($DryRun) {
        Write-Log "Dry-run mode enabled."
        Write-Log "Running focused orchestration and CLI tests."
        Write-Log "No database or live odds work will be executed."

        & $PythonPath -m pytest `
            tests\orchestration\test_moneyline_daily.py `
            tests\orchestration\test_moneyline_daily_cli.py `
            -q 2>&1 |
            ForEach-Object {
                $Line = $_.ToString()
                Write-Host $Line
                Add-Content -Path $LogPath -Value $Line
            }

        $PythonExitCode = $LASTEXITCODE

        if ($PythonExitCode -ne 0) {
            throw "Daily pregame dry run exited with code $PythonExitCode."
        }

        Write-Log "Daily pregame dry run completed successfully."
        Write-Log "No live pregame pipeline work was executed."
        Write-Log "Log file: $LogPath"

        exit 0
    }

    . $DatabaseReadinessPath
    . $ScheduledExecutionGuardPath
    . $RetryHelperPath

    $ScheduledExecutionLogger = {
        param([string]$Message)
        Write-Log $Message
    }

    $DatabaseLogger = {
        param([string]$Message)
        Write-Log $Message
    }

    $PregamePreflight = {
        $null = Assert-MoneylineScheduledExecutionValid `
            -PythonPath $PythonPath `
            -SourcePath $SourcePath `
            -TaskIdentity "moneyline_pregame" `
            -Logger $ScheduledExecutionLogger

        Write-Log "Checking SportsModel database readiness."
        Wait-SportsModelDatabaseReady `
            -PythonPath $PythonPath `
            -SourcePath $SourcePath `
            -TimeoutSeconds 600 `
            -PollSeconds 15 `
            -Logger $DatabaseLogger
        Write-Log "Database readiness check completed."

        return Assert-MoneylineScheduledExecutionValid `
            -PythonPath $PythonPath `
            -SourcePath $SourcePath `
            -TaskIdentity "moneyline_pregame" `
            -EnforceCanonicalPregameDeadline `
            -ReturnValidity `
            -Logger $ScheduledExecutionLogger
    }

    $PregameOperation = {
        & $PythonPath $ScriptPath 2>&1 |
            ForEach-Object {
                $Line = $_.ToString()
                Write-Host $Line
                Add-Content -Path $LogPath -Value $Line
            }

        return $LASTEXITCODE
    }

    $PregameRetryDeadlineProvider = {
        return Assert-MoneylineScheduledExecutionValid `
            -PythonPath $PythonPath `
            -SourcePath $SourcePath `
            -TaskIdentity "moneyline_pregame" `
            -EnforceCanonicalPregameDeadline `
            -ReturnValidity `
            -Logger $ScheduledExecutionLogger
    }

    Invoke-MoneylineOperationWithRetry `
        -OperationName "Daily Moneyline Pregame" `
        -Preflight $PregamePreflight `
        -Operation $PregameOperation `
        -RetryDeadlineProvider $PregameRetryDeadlineProvider `
        -MaxAttempts 4 `
        -RetryDelaySeconds 900 `
        -Logger $ScheduledExecutionLogger

    Write-Log "Daily Moneyline pregame workflow completed successfully."
    Write-Log "Log file: $LogPath"

    exit 0
}
catch {
    Write-Log "ERROR: $($_.Exception.Message)"
    Write-Log "Daily Moneyline pregame workflow failed."
    Write-Log "Log file: $LogPath"

    exit 1
}




