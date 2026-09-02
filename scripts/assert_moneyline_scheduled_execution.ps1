function Assert-MoneylineScheduledExecutionValid {
    [CmdletBinding()]
    param(
        [Parameter(Mandatory)]
        [string]$PythonPath,

        [Parameter(Mandatory)]
        [string]$SourcePath,

        [Parameter(Mandatory)]
        [ValidateSet(
            "moneyline_odds_snapshot",
            "moneyline_pregame",
            "moneyline_postgame",
            "moneyline_tomorrow_preview"
        )]
        [string]$TaskIdentity,

        [ValidateSet(
            "opening",
            "evening",
            "late_night",
            "morning",
            "afternoon"
        )]
        [string]$SnapshotRole,

        [scriptblock]$Logger
    )

    $PreviousPythonPath = $env:PYTHONPATH
    $PreviousErrorActionPreference = $ErrorActionPreference

    try {
        $env:PYTHONPATH = $SourcePath
        $ErrorActionPreference = "Continue"
        $Arguments = @(
            "-m",
            "sportsmodel.orchestration.scheduled_execution_cli",
            "--task-identity",
            $TaskIdentity
        )

        if (-not [string]::IsNullOrWhiteSpace($SnapshotRole)) {
            $Arguments += @(
                "--snapshot-role",
                $SnapshotRole
            )
        }

        $ValidityOutput = @(
            & $PythonPath @Arguments 2>&1
        )
        $ValidityExitCode = $LASTEXITCODE
    }
    finally {
        $env:PYTHONPATH = $PreviousPythonPath
        $ErrorActionPreference = $PreviousErrorActionPreference
    }

    foreach ($OutputLine in $ValidityOutput) {
        $Message = $OutputLine.ToString()

        if ($null -ne $Logger) {
            & $Logger $Message
        }
        else {
            Write-Host $Message
        }
    }

    if ($ValidityExitCode -ne 0) {
        throw (
            "Scheduled execution validity check refused task " +
            "$TaskIdentity before live workflow or provider execution."
        )
    }
}
