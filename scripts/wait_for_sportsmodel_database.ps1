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

        [string]$ExpectedServiceName = "SportsModelPostgreSQL16",

        [string]$ExpectedServiceExecutable = (
            "D:\PostgreSQL\16\server\bin\pg_ctl.exe"
        ),

        [string]$ExpectedDataDirectory = "D:\PostgreSQL\16\data",

        [int]$ExpectedPort = 5432,

        [string]$ExpectedDatabase = "sportsmodel",

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


    function New-ReadinessResult {
        param(
            [Parameter(Mandatory)]
            [ValidateSet("ready", "transient", "permanent")]
            [string]$Status,

            [Parameter(Mandatory)]
            [string]$Message
        )

        return [pscustomobject]@{
            Status = $Status
            Message = $Message
        }
    }


    function New-ReadinessException {
        param(
            [Parameter(Mandatory)]
            [string]$Status,

            [Parameter(Mandatory)]
            [string]$Message
        )

        $Exception = [InvalidOperationException]::new($Message)
        $Exception.Data["SportsModelFailureClassification"] = $Status
        return $Exception
    }


    function Test-SportsModelNativePostgreSQLIdentity {
        try {
            $Service = Get-CimInstance `
                Win32_Service `
                -Filter "Name='$ExpectedServiceName'" `
                -ErrorAction Stop
        }
        catch {
            return New-ReadinessResult `
                -Status "permanent" `
                -Message (
                    "Unable to inspect Windows service " +
                    "$ExpectedServiceName."
                )
        }

        if ($null -eq $Service) {
            return New-ReadinessResult `
                -Status "permanent" `
                -Message (
                    "Expected Windows service $ExpectedServiceName " +
                    "was not found."
                )
        }

        $ServicePath = [string]$Service.PathName
        $ExecutableIndex = $ServicePath.IndexOf(
            $ExpectedServiceExecutable,
            [StringComparison]::OrdinalIgnoreCase
        )
        $DataDirectoryIndex = $ServicePath.IndexOf(
            $ExpectedDataDirectory,
            [StringComparison]::OrdinalIgnoreCase
        )

        if ($ExecutableIndex -lt 0 -or $DataDirectoryIndex -lt 0) {
            return New-ReadinessResult `
                -Status "permanent" `
                -Message (
                    "Windows service $ExpectedServiceName does not use " +
                    "the expected native PostgreSQL installation and " +
                    "data directory."
                )
        }

        if ($Service.StartMode -ne "Auto") {
            return New-ReadinessResult `
                -Status "permanent" `
                -Message (
                    "Windows service $ExpectedServiceName is not " +
                    "configured for automatic startup."
                )
        }

        $ServiceRunning = (
            $Service.State -eq "Running" `
            -and $Service.ProcessId -gt 0
        )

        if ($ServiceRunning) {
            try {
                $ServiceProcess = Get-CimInstance `
                    Win32_Process `
                    -Filter "ProcessId=$($Service.ProcessId)" `
                    -ErrorAction Stop
            }
            catch {
                return New-ReadinessResult `
                    -Status "permanent" `
                    -Message (
                        "Unable to inspect the $ExpectedServiceName " +
                        "service process."
                    )
            }

            if (
                $null -eq $ServiceProcess `
                -or $ServiceProcess.Name -ine "pg_ctl.exe"
            ) {
                return New-ReadinessResult `
                    -Status "permanent" `
                    -Message (
                        "Windows service $ExpectedServiceName is not owned " +
                        "by the expected pg_ctl.exe process."
                    )
            }
        }

        try {
            $Listeners = @(
                Get-NetTCPConnection `
                    -State Listen `
                    -ErrorAction Stop |
                    Where-Object { $_.LocalPort -eq $ExpectedPort }
            )
        }
        catch {
            return New-ReadinessResult `
                -Status "permanent" `
                -Message (
                    "Unable to inspect localhost port $ExpectedPort " +
                    "listener ownership."
                )
        }

        if ($Listeners.Count -eq 0) {
            if ($ServiceRunning) {
                $ListenerMessage = (
                    "Native PostgreSQL has not opened localhost port " +
                    "$ExpectedPort yet."
                )
            }
            else {
                $ListenerMessage = (
                    "Windows service $ExpectedServiceName is not " +
                    "running yet."
                )
            }

            return New-ReadinessResult `
                -Status "transient" `
                -Message $ListenerMessage
        }

        if (-not $ServiceRunning) {
            return New-ReadinessResult `
                -Status "permanent" `
                -Message (
                    "Port $ExpectedPort has a listener while Windows " +
                    "service $ExpectedServiceName is not running."
                )
        }

        $UnexpectedAddresses = @(
            $Listeners |
                Where-Object {
                    $_.LocalAddress -notin @("127.0.0.1", "::1")
                }
        )

        if ($UnexpectedAddresses.Count -gt 0) {
            return New-ReadinessResult `
                -Status "permanent" `
                -Message (
                    "PostgreSQL port $ExpectedPort is not restricted " +
                    "to loopback listeners."
                )
        }

        $ListenerProcessIds = @(
            $Listeners |
                Select-Object -ExpandProperty OwningProcess -Unique
        )

        if ($ListenerProcessIds.Count -ne 1) {
            return New-ReadinessResult `
                -Status "permanent" `
                -Message (
                    "PostgreSQL port $ExpectedPort does not have one " +
                    "demonstrable native process owner."
                )
        }

        try {
            $ListenerProcess = Get-CimInstance `
                Win32_Process `
                -Filter "ProcessId=$($ListenerProcessIds[0])" `
                -ErrorAction Stop
        }
        catch {
            return New-ReadinessResult `
                -Status "permanent" `
                -Message (
                    "Unable to inspect the PostgreSQL port " +
                    "$ExpectedPort listener process."
                )
        }

        if (
            $null -eq $ListenerProcess `
            -or $ListenerProcess.Name -ine "postgres.exe" `
            -or $ListenerProcess.ParentProcessId -ne $Service.ProcessId
        ) {
            return New-ReadinessResult `
                -Status "permanent" `
                -Message (
                    "PostgreSQL port $ExpectedPort is not owned by the " +
                    "postgres.exe child of Windows service " +
                    "$ExpectedServiceName."
                )
        }

        return New-ReadinessResult `
            -Status "ready" `
            -Message (
                "Windows service and localhost:$ExpectedPort listener " +
                "identity are valid."
            )
    }


    function Invoke-SportsModelDatabaseProbe {
        $PreviousPythonPath = $env:PYTHONPATH
        $PreviousErrorActionPreference = $ErrorActionPreference

        try {
            $env:PYTHONPATH = $SourcePath
            $ErrorActionPreference = "Continue"

            $ProbeOutput = @(
                & $PythonPath `
                    -m sportsmodel.database.readiness_probe `
                    --expected-port $ExpectedPort `
                    --expected-database $ExpectedDatabase `
                    2>&1
            )
            $ProbeExitCode = $LASTEXITCODE
        }
        finally {
            $env:PYTHONPATH = $PreviousPythonPath
            $ErrorActionPreference = $PreviousErrorActionPreference
        }

        $ProbeMessage = (
            $ProbeOutput |
                ForEach-Object { $_.ToString() } |
                Where-Object { -not [string]::IsNullOrWhiteSpace($_) } |
                Select-Object -Last 1
        )

        if ([string]::IsNullOrWhiteSpace($ProbeMessage)) {
            $ProbeMessage = "Database readiness probe returned no details."
        }

        switch ($ProbeExitCode) {
            0 {
                return New-ReadinessResult `
                    -Status "ready" `
                    -Message $ProbeMessage
            }
            10 {
                return New-ReadinessResult `
                    -Status "transient" `
                    -Message $ProbeMessage
            }
            20 {
                return New-ReadinessResult `
                    -Status "permanent" `
                    -Message $ProbeMessage
            }
            default {
                return New-ReadinessResult `
                    -Status "permanent" `
                    -Message (
                        "Database readiness probe returned unexpected " +
                        "exit code $ProbeExitCode."
                    )
            }
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

    if ($ExpectedPort -lt 1 -or $ExpectedPort -gt 65535) {
        throw "ExpectedPort must be between 1 and 65535."
    }

    if ([string]::IsNullOrWhiteSpace($ExpectedDatabase)) {
        throw "ExpectedDatabase must not be empty."
    }


    $Timer = [Diagnostics.Stopwatch]::StartNew()
    $NextProgressLogSeconds = 60
    $LastTransientMessage = "Native PostgreSQL is not ready."
    $InitialWaitLogged = $false

    while ($true) {
        $IdentityResult = Test-SportsModelNativePostgreSQLIdentity

        if ($IdentityResult.Status -eq "permanent") {
            throw (New-ReadinessException -Status "permanent" -Message (
                "SportsModel database readiness failed permanently: " +
                "$($IdentityResult.Message) No database service was " +
                "started automatically."
            ))
        }

        if ($IdentityResult.Status -eq "ready") {
            $DatabaseResult = Invoke-SportsModelDatabaseProbe

            if ($DatabaseResult.Status -eq "ready") {
                Write-ReadinessLog (
                    "SportsModel database readiness: READY. " +
                    "$($IdentityResult.Message) " +
                    "$($DatabaseResult.Message)"
                )
                return
            }

            if ($DatabaseResult.Status -eq "permanent") {
                throw (New-ReadinessException -Status "permanent" -Message (
                    "SportsModel database readiness failed permanently: " +
                    "$($DatabaseResult.Message) No database service was " +
                    "started automatically."
                ))
            }

            $LastTransientMessage = $DatabaseResult.Message
        }
        else {
            $LastTransientMessage = $IdentityResult.Message
        }

        if (-not $InitialWaitLogged) {
            Write-ReadinessLog (
                "SportsModel native PostgreSQL is temporarily " +
                "unavailable. $LastTransientMessage Waiting up to " +
                "$TimeoutSeconds seconds; no database service will be " +
                "started automatically."
            )
            $InitialWaitLogged = $true
        }

        $RemainingMilliseconds = (
            ($TimeoutSeconds * 1000) - $Timer.ElapsedMilliseconds
        )

        if ($RemainingMilliseconds -le 0) {
            break
        }

        if (
            $Timer.Elapsed.TotalSeconds -ge
            $NextProgressLogSeconds
        ) {
            $ElapsedSeconds = [int]$Timer.Elapsed.TotalSeconds
            Write-ReadinessLog (
                "Still waiting for native PostgreSQL. " +
                "Elapsed: $ElapsedSeconds seconds. " +
                "$LastTransientMessage"
            )
            $NextProgressLogSeconds += 60
        }

        $SleepMilliseconds = [math]::Min(
            $PollSeconds * 1000,
            $RemainingMilliseconds
        )
        Start-Sleep -Milliseconds $SleepMilliseconds
    }

    $Timer.Stop()

    throw (New-ReadinessException -Status "transient" -Message (
        "SportsModel native PostgreSQL did not become ready within " +
        "$TimeoutSeconds seconds. Last condition: " +
        "$LastTransientMessage Verify Windows service " +
        "'$ExpectedServiceName' and localhost:$ExpectedPort. No " +
        "database service was started automatically."
    ))
}
