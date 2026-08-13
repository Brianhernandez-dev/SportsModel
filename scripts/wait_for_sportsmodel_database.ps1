Set-StrictMode -Version Latest


function Wait-SportsModelDatabaseReady {
    [CmdletBinding()]
    param(
        [Parameter(Mandatory)]
        [string]$PythonPath,

        [Parameter(Mandatory)]
        [string]$SourcePath,

        [int]$TimeoutSeconds = 600,

        [int]$PollSeconds = 15,

        [scriptblock]$Logger
    )

    function Write-ReadinessLog {
        param(
            [Parameter(Mandatory)]
            [string]$Message
        )

        if ($null -ne $Logger) {
            & $Logger $Message
            return
        }

        Write-Host $Message
    }


    function Test-SportsModelDatabaseConnection {
        $PreviousPythonPath = $env:PYTHONPATH

        try {
            $env:PYTHONPATH = $SourcePath

            & $PythonPath `
                -c `
                "from sportsmodel.database.connection import get_connection; connection = get_connection(); connection.close()" `
                *> $null

            return ($LASTEXITCODE -eq 0)
        }
        finally {
            $env:PYTHONPATH = $PreviousPythonPath
        }
    }


    if (-not (Test-Path $PythonPath)) {
        throw "Python executable was not found: $PythonPath"
    }

    if (-not (Test-Path $SourcePath)) {
        throw "SportsModel source path was not found: $SourcePath"
    }

    if ($TimeoutSeconds -le 0) {
        throw "TimeoutSeconds must be greater than zero."
    }

    if ($PollSeconds -le 0) {
        throw "PollSeconds must be greater than zero."
    }


    if (Test-SportsModelDatabaseConnection) {
        Write-ReadinessLog `
            "SportsModel database readiness: READY"

        return
    }


    Write-ReadinessLog `
        "SportsModel database is unavailable. Beginning recovery wait."

    $DockerCommand = Get-Command `
        docker.exe `
        -ErrorAction SilentlyContinue

    if ($null -eq $DockerCommand) {
        Write-ReadinessLog `
            "Docker CLI was not found. Will continue waiting for PostgreSQL."
    }
    else {
        $DockerPath = $DockerCommand.Source

        $DesktopStatus = (
            & $DockerPath desktop status 2>&1 |
            Out-String
        )

        $DesktopRunning = (
            $LASTEXITCODE -eq 0 -and
            $DesktopStatus -match "(?im)^\s*Status\s+running\s*$"
        )

        if ($DesktopRunning) {
            Write-ReadinessLog `
                "Docker Desktop reports running. Waiting for PostgreSQL."
        }
        else {
            Write-ReadinessLog `
                "Docker Desktop is not running. Requesting Docker Desktop start."

            $StartOutput = (
                & $DockerPath desktop start 2>&1 |
                Out-String
            ).Trim()

            $StartExitCode = $LASTEXITCODE

            if ($StartOutput) {
                Write-ReadinessLog `
                    "Docker Desktop start response: $StartOutput"
            }

            if ($StartExitCode -ne 0) {
                Write-ReadinessLog (
                    "Docker Desktop start returned exit code " +
                    "$StartExitCode. Continuing readiness wait."
                )
            }
        }
    }


    $StartedAt = Get-Date
    $Deadline = $StartedAt.AddSeconds($TimeoutSeconds)
    $Attempt = 0

    while ((Get-Date) -lt $Deadline) {
        $Attempt += 1

        Start-Sleep -Seconds $PollSeconds

        if (Test-SportsModelDatabaseConnection) {
            $Elapsed = [math]::Round(
                ((Get-Date) - $StartedAt).TotalSeconds
            )

            Write-ReadinessLog (
                "SportsModel database readiness: READY " +
                "after $Elapsed seconds."
            )

            return
        }

        $ElapsedSeconds = [int](
            ((Get-Date) - $StartedAt).TotalSeconds
        )

        if ($ElapsedSeconds -gt 0 -and ($ElapsedSeconds % 60) -lt $PollSeconds) {
            Write-ReadinessLog (
                "Still waiting for PostgreSQL. " +
                "Elapsed: $ElapsedSeconds seconds."
            )
        }
    }


    throw (
        "SportsModel database did not become ready within " +
        "$TimeoutSeconds seconds."
    )
}
