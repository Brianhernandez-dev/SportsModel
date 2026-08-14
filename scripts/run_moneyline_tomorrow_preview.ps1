param(
    [switch]$DryRun
)

$ErrorActionPreference = "Stop"

$ProjectRoot = Split-Path -Parent $PSScriptRoot
$PythonPath = "D:\SportsModel\.venv\Scripts\python.exe"
$SourcePath = Join-Path $ProjectRoot "src"
$EnvironmentPath = "D:\SportsModel\.env"
$PreviewScriptPath = Join-Path `
    $ProjectRoot `
    "scripts\preview_mlb_moneyline.py"
$PreviewModulePath = Join-Path `
    $SourcePath `
    "sportsmodel\predictions\moneyline_preview_cli.py"
$OpeningTaskName = "SportsModel - Moneyline Opening Snapshot"
$LogDirectory = Join-Path `
    $ProjectRoot `
    "logs\moneyline_tomorrow_preview"

$PacificTimeZone = [TimeZoneInfo]::FindSystemTimeZoneById(
    "Pacific Standard Time"
)
$PacificNow = [TimeZoneInfo]::ConvertTime(
    [DateTimeOffset]::UtcNow,
    $PacificTimeZone
)
$TargetDate = $PacificNow.Date.AddDays(1).ToString("yyyy-MM-dd")
$LogPath = Join-Path $LogDirectory "preview_$TargetDate.log"

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
    Add-Content -Path $LogPath -Value $Line -Encoding ASCII
}

try {
    if (-not (Test-Path $LogDirectory)) {
        New-Item `
            -ItemType Directory `
            -Path $LogDirectory `
            -Force |
            Out-Null
    }

    Write-Log "Tomorrow Preview wrapper started. Target date: $TargetDate"

    foreach ($RequiredPath in @(
        $PythonPath,
        $SourcePath,
        $EnvironmentPath,
        $PreviewScriptPath,
        $PreviewModulePath
    )) {
        if (-not (Test-Path $RequiredPath)) {
            throw "Required path was not found: $RequiredPath"
        }
    }

    Set-Location $ProjectRoot
    $env:PYTHONPATH = $SourcePath
    $env:SPORTSMODEL_ENV_FILE = $EnvironmentPath
    $env:PYTHONUNBUFFERED = "1"

    if ($DryRun) {
        Write-Log "Dry-run validation requested."

        $ResolvedModulePath = (& $PythonPath -c (
            "import sportsmodel.predictions.moneyline_preview_cli as m; " +
            "print(m.__file__)"
        ) | Select-Object -Last 1).Trim()

        if ($LASTEXITCODE -ne 0) {
            throw "Preview module resolution failed."
        }

        if (
            [System.IO.Path]::GetFullPath($ResolvedModulePath) -ne
            [System.IO.Path]::GetFullPath($PreviewModulePath)
        ) {
            throw (
                "Preview module resolved outside the project root: " +
                "$ResolvedModulePath"
            )
        }

        & $PythonPath $PreviewScriptPath --help

        if ($LASTEXITCODE -ne 0) {
            throw (
                "Preview CLI help check failed with exit code " +
                "$LASTEXITCODE."
            )
        }

        Write-Log "Dry-run validation completed successfully."
        Write-Log "No database or prediction work was executed."
        exit 0
    }

    Write-Log "Checking opening snapshot task."

    for ($Attempt = 1; $Attempt -le 20; $Attempt++) {
        $OpeningTask = Get-ScheduledTask -TaskName $OpeningTaskName

        if ($OpeningTask.State -ne "Running") {
            break
        }

        Write-Log (
            "Opening snapshot is still running. Waiting 30 seconds. " +
            "Attempt $Attempt/20."
        )
        Start-Sleep -Seconds 30
    }

    $OpeningTask = Get-ScheduledTask -TaskName $OpeningTaskName

    if ($OpeningTask.State -eq "Running") {
        throw "Opening snapshot did not finish before preview timeout."
    }

    $OpeningInfo = Get-ScheduledTaskInfo -TaskName $OpeningTaskName

    if ($OpeningInfo.LastRunTime.Date -ne $PacificNow.Date) {
        throw (
            "Opening snapshot has not run today. Last run: " +
            "$($OpeningInfo.LastRunTime)."
        )
    }

    if ($OpeningInfo.LastTaskResult -ne 0) {
        throw (
            "Opening snapshot task failed with result " +
            "$($OpeningInfo.LastTaskResult)."
        )
    }

    Write-Log "Opening snapshot verified successfully."
    Write-Log "Starting Tomorrow Preview generation."

    $PreviewOutput = & $PythonPath `
        $PreviewScriptPath `
        --target-date $TargetDate `
        2>&1
    $PreviewExitCode = $LASTEXITCODE

    foreach ($OutputLine in $PreviewOutput) {
        Write-Log "$OutputLine"
    }

    if ($PreviewExitCode -ne 0) {
        throw (
            "Tomorrow Preview failed with exit code " +
            "$PreviewExitCode."
        )
    }

    Write-Log "Tomorrow Preview completed successfully for $TargetDate."
    exit 0
}
catch {
    Write-Log "ERROR: $($_.Exception.Message)"
    Write-Log "Log file: $LogPath"
    exit 1
}
