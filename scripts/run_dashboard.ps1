[CmdletBinding()]
param(
    [ValidateRange(1, 65535)]
    [int]$Port = 8501
)

$ErrorActionPreference = "Stop"

$repositoryRoot = Split-Path -Parent $PSScriptRoot
$sourcePath = Join-Path $repositoryRoot "src"
$appPath = Join-Path `
    $sourcePath `
    "sportsmodel\dashboard\app.py"
$databaseReadinessPath = Join-Path `
    $PSScriptRoot `
    "wait_for_sportsmodel_database.ps1"
$startupEvidencePath = Join-Path `
    $PSScriptRoot `
    "dashboard_startup_evidence.ps1"
$logDirectory = Join-Path $repositoryRoot "logs\dashboard"

. $startupEvidencePath

$startupEvidence = New-SportsModelDashboardStartupEvidence `
    -LogDirectory $logDirectory

Write-SportsModelDashboardStartupEvidence `
    -Evidence $startupEvidence `
    -Message (
        "Launcher invocation started. Launcher PID=$PID; port=$Port."
    )

try {
    . (Join-Path $PSScriptRoot "dashboard_health.ps1")
    . $databaseReadinessPath

    if (-not ("SportsModel.DashboardJobObject" -as [type])) {
        Add-Type -TypeDefinition @"
using System;
using System.Runtime.InteropServices;

namespace SportsModel {
    public static class DashboardJobObject {
        private const UInt32 JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE = 0x00002000;
        private const Int32 JobObjectExtendedLimitInformation = 9;

        [StructLayout(LayoutKind.Sequential)]
        private struct JOBOBJECT_BASIC_LIMIT_INFORMATION {
            public Int64 PerProcessUserTimeLimit;
            public Int64 PerJobUserTimeLimit;
            public UInt32 LimitFlags;
            public UIntPtr MinimumWorkingSetSize;
            public UIntPtr MaximumWorkingSetSize;
            public UInt32 ActiveProcessLimit;
            public UIntPtr Affinity;
            public UInt32 PriorityClass;
            public UInt32 SchedulingClass;
        }

        [StructLayout(LayoutKind.Sequential)]
        private struct IO_COUNTERS {
            public UInt64 ReadOperationCount;
            public UInt64 WriteOperationCount;
            public UInt64 OtherOperationCount;
            public UInt64 ReadTransferCount;
            public UInt64 WriteTransferCount;
            public UInt64 OtherTransferCount;
        }

        [StructLayout(LayoutKind.Sequential)]
        private struct JOBOBJECT_EXTENDED_LIMIT_INFORMATION {
            public JOBOBJECT_BASIC_LIMIT_INFORMATION BasicLimitInformation;
            public IO_COUNTERS IoInfo;
            public UIntPtr ProcessMemoryLimit;
            public UIntPtr JobMemoryLimit;
            public UIntPtr PeakProcessMemoryUsed;
            public UIntPtr PeakJobMemoryUsed;
        }

        [DllImport(
            "kernel32.dll",
            CharSet = CharSet.Unicode,
            SetLastError = true
        )]
        private static extern IntPtr CreateJobObject(
            IntPtr jobAttributes,
            string name
        );

        [DllImport("kernel32.dll", SetLastError = true)]
        private static extern bool SetInformationJobObject(
            IntPtr job,
            Int32 informationClass,
            ref JOBOBJECT_EXTENDED_LIMIT_INFORMATION information,
            UInt32 informationLength
        );

        [DllImport("kernel32.dll", SetLastError = true)]
        public static extern bool AssignProcessToJobObject(
            IntPtr job,
            IntPtr process
        );

        [DllImport("kernel32.dll", SetLastError = true)]
        public static extern bool CloseHandle(IntPtr handle);

        public static IntPtr CreateKillOnCloseJob() {
            IntPtr job = CreateJobObject(IntPtr.Zero, null);
            if (job == IntPtr.Zero) {
                throw new System.ComponentModel.Win32Exception();
            }

            JOBOBJECT_EXTENDED_LIMIT_INFORMATION information =
                new JOBOBJECT_EXTENDED_LIMIT_INFORMATION();
            information.BasicLimitInformation.LimitFlags =
                JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE;

            if (!SetInformationJobObject(
                job,
                JobObjectExtendedLimitInformation,
                ref information,
                (UInt32)Marshal.SizeOf(information)
            )) {
                CloseHandle(job);
                throw new System.ComponentModel.Win32Exception();
            }

            return job;
        }
    }
}
"@
    }
}
catch {
    Write-SportsModelDashboardStartupEvidence `
        -Evidence $startupEvidence `
        -Message (
            "Final startup failure. Stage=launcher-initialization; " +
            "error type=$($_.Exception.GetType().FullName)."
        )
    Write-Error -ErrorAction Continue $_
    exit 1
}

function Stop-OwnedProcessTree {
    param(
        [Parameter(Mandatory = $true)]
        [int]$OwnedProcessId
    )

    $taskKillPath = Join-Path $env:SystemRoot "System32\taskkill.exe"
    $result = Start-Process `
        -FilePath $taskKillPath `
        -ArgumentList @("/PID", $OwnedProcessId, "/T", "/F") `
        -WindowStyle Hidden `
        -Wait `
        -PassThru

    if ($result.ExitCode -ne 0) {
        Write-Warning (
            "Unable to terminate owned dashboard process tree " +
            "$OwnedProcessId; taskkill exit code $($result.ExitCode)."
        )
    }
}

function Test-KnownDashboardListener {
    param(
        [Parameter(Mandatory = $true)]
        [int]$ListenerProcessId,

        [Parameter(Mandatory = $true)]
        [string]$ExpectedAppPath,

        [Parameter(Mandatory = $true)]
        [int]$ExpectedPort
    )

    $process = Get-CimInstance `
        Win32_Process `
        -Filter "ProcessId = $ListenerProcessId" `
        -ErrorAction SilentlyContinue

    if (-not $process -or -not $process.CommandLine) {
        return $false
    }

    $commandLine = $process.CommandLine
    return (
        $process.Name -ieq "python.exe" `
        -and $commandLine -like "*-m streamlit*" `
        -and $commandLine -like "*$ExpectedAppPath*" `
        -and $commandLine -like "*--server.port=$ExpectedPort*"
    )
}

$startupStage = "python-resolution"

try {
    $env:PYTHONPATH = $sourcePath
    $env:SPORTSMODEL_ENV_FILE = Join-Path $repositoryRoot ".env"

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
}
catch {
    Write-SportsModelDashboardStartupEvidence `
        -Evidence $startupEvidence `
        -Message (
            "Final startup failure. Stage=$startupStage; " +
            "error type=$($_.Exception.GetType().FullName)."
        )
    Write-Error -ErrorAction Continue $_
    exit 1
}

$startupStage = "database-readiness"

try {
    Write-SportsModelDashboardStartupEvidence `
        -Evidence $startupEvidence `
        -Message "Database readiness check started."

    $databaseLogger = {
        param([string]$Message)
        Write-SportsModelDashboardStartupEvidence `
            -Evidence $startupEvidence `
            -Message "Database readiness: $Message"
    }

    Wait-SportsModelDatabaseReady `
        -PythonPath $pythonPath `
        -SourcePath $sourcePath `
        -TimeoutSeconds 600 `
        -PollSeconds 15 `
        -Logger $databaseLogger

    Write-SportsModelDashboardStartupEvidence `
        -Evidence $startupEvidence `
        -Message "Database readiness check succeeded."

    $startupStage = "production-read-probe"
    Write-SportsModelDashboardStartupEvidence `
        -Evidence $startupEvidence `
        -Message "Production read probe started."

    $readProbeOutput = @(
        & $pythonPath `
            -m sportsmodel.dashboard.startup_probe `
            2>&1
    )
    $readProbeExitCode = $LASTEXITCODE

    $readProbeMessage = @(
        $readProbeOutput |
            ForEach-Object { $_.ToString() } |
            Where-Object { -not [string]::IsNullOrWhiteSpace($_) }
    ) | Select-Object -Last 1

    if ($readProbeExitCode -ne 0) {
        Write-SportsModelDashboardStartupEvidence `
            -Evidence $startupEvidence `
            -Message (
                "Production read probe failed; exit code=" +
                "$readProbeExitCode."
            )
        throw (
            "Dashboard production read probe failed with exit code " +
            "$readProbeExitCode."
        )
    }

    if (
        [string]::IsNullOrWhiteSpace($readProbeMessage) `
        -or $readProbeMessage -notlike (
            "Dashboard production read probe: READY.*"
        )
    ) {
        Write-SportsModelDashboardStartupEvidence `
            -Evidence $startupEvidence `
            -Message "Production read probe failed; invalid result."
        throw "Dashboard production read probe returned an invalid result."
    }

    Write-SportsModelDashboardStartupEvidence `
        -Evidence $startupEvidence `
        -Message $readProbeMessage

    Write-SportsModelDashboardStartupEvidence `
        -Evidence $startupEvidence `
        -Message "Production read probe succeeded."

    $startupStage = "listener-validation"
    $existingListeners = @(
        Get-NetTCPConnection `
            -LocalAddress "127.0.0.1" `
            -LocalPort $Port `
            -State Listen `
            -ErrorAction SilentlyContinue
    )

    foreach ($listener in $existingListeners) {
        if (-not (Test-KnownDashboardListener `
            -ListenerProcessId $listener.OwningProcess `
            -ExpectedAppPath $appPath `
            -ExpectedPort $Port
        )) {
            throw (
                "Port $Port is owned by an unverified process " +
                "$($listener.OwningProcess). Refusing to terminate it."
            )
        }

        Write-SportsModelDashboardStartupEvidence `
            -Evidence $startupEvidence `
            -Message (
                "Stopping proven stale SportsModel dashboard listener " +
                "PID=$($listener.OwningProcess); port=$Port."
            )
        Stop-OwnedProcessTree -OwnedProcessId $listener.OwningProcess
    }

    $remainingListener = Get-NetTCPConnection `
        -LocalAddress "127.0.0.1" `
        -LocalPort $Port `
        -State Listen `
        -ErrorAction SilentlyContinue

    if ($remainingListener) {
        throw "Port $Port remained occupied after stale-listener cleanup."
    }
}
catch {
    if ($startupStage -eq "database-readiness") {
        Write-SportsModelDashboardStartupEvidence `
            -Evidence $startupEvidence `
            -Message "Database readiness check failed."
    }

    Write-SportsModelDashboardStartupEvidence `
        -Evidence $startupEvidence `
        -Message (
            "Final startup failure. Stage=$startupStage; " +
            "error type=$($_.Exception.GetType().FullName)."
        )
    Write-Error -ErrorAction Continue $_
    exit 1
}

Write-Host "SportsModel dashboard"
Write-Host "Repository: $repositoryRoot"
Write-Host "Python:     $pythonPath"
Write-Host "Address:    http://127.0.0.1:$Port"

$streamlitArguments = @(
    "-m",
    "streamlit",
    "run",
    ('"{0}"' -f $appPath),
    "--server.address=127.0.0.1",
    "--server.port=$Port",
    "--server.headless=true"
)

$jobHandle = [IntPtr]::Zero
$childProcess = $null
$wrapperExitCode = 1
$assignedToJob = $false
$startupSucceeded = $false

try {
    $startupStage = "streamlit-process-launch"
    $jobHandle = (
        [SportsModel.DashboardJobObject]::CreateKillOnCloseJob()
    )

    $childProcess = Start-Process `
        -FilePath $pythonPath `
        -ArgumentList $streamlitArguments `
        -WorkingDirectory $repositoryRoot `
        -WindowStyle Hidden `
        -PassThru

    $assignedToJob = (
        [SportsModel.DashboardJobObject]::AssignProcessToJobObject(
            $jobHandle,
            $childProcess.Handle
        )
    )

    if (-not $assignedToJob) {
        throw "Unable to assign the dashboard child to its Windows job object."
    }

    Write-SportsModelDashboardStartupEvidence `
        -Evidence $startupEvidence `
        -Message (
            "Streamlit process started and assigned to launcher-owned " +
            "Job Object. Streamlit PID=$($childProcess.Id); " +
            "launcher PID=$PID."
        )

    $startupDeadline = [DateTime]::UtcNow.AddSeconds(60)
    $consecutiveHealthFailures = 0
    $startupStage = "streamlit-http-health"

    while (-not $childProcess.WaitForExit(5000)) {
        $health = Get-SportsModelDashboardHealth `
            -Port $Port `
            -TimeoutSeconds 3

        if ($health.Healthy) {
            $consecutiveHealthFailures = 0

            if (-not $startupSucceeded) {
                Write-SportsModelDashboardStartupEvidence `
                    -Evidence $startupEvidence `
                    -Message (
                        "HTTP health succeeded. Listener=True; " +
                        "status=$($health.HttpStatusCode); " +
                        "URL=$($health.HealthUrl)."
                    )
                Write-SportsModelDashboardStartupEvidence `
                    -Evidence $startupEvidence `
                    -Message "Final startup success."
                $startupSucceeded = $true
            }

            continue
        }

        if ([DateTime]::UtcNow -lt $startupDeadline) {
            continue
        }

        $consecutiveHealthFailures++
        Write-Warning (
            "Dashboard health failure " +
            "$consecutiveHealthFailures/3: $($health.ErrorMessage)"
        )

        if ($consecutiveHealthFailures -ge 3) {
            throw (
                "Dashboard remained unhealthy for three consecutive checks."
            )
        }
    }

    $childExitCode = $childProcess.ExitCode
    Write-Warning (
        "Dashboard process exited unexpectedly with code $childExitCode."
    )
    Write-SportsModelDashboardStartupEvidence `
        -Evidence $startupEvidence `
        -Message (
            "Final launcher failure. Streamlit exited unexpectedly; " +
            "exit code=$childExitCode."
        )
    $wrapperExitCode = if ($childExitCode -eq 0) { 1 } else { $childExitCode }
}
catch {
    Write-SportsModelDashboardStartupEvidence `
        -Evidence $startupEvidence `
        -Message (
            "Final startup failure. Stage=$startupStage; " +
            "error type=$($_.Exception.GetType().FullName)."
        )
    Write-Error -ErrorAction Continue $_
    $wrapperExitCode = 1
}
finally {
    if ($jobHandle -ne [IntPtr]::Zero) {
        [void][SportsModel.DashboardJobObject]::CloseHandle($jobHandle)
        $jobHandle = [IntPtr]::Zero
    }

    if (
        $childProcess `
        -and -not $childProcess.HasExited
    ) {
        Stop-OwnedProcessTree -OwnedProcessId $childProcess.Id
    }
}

exit $wrapperExitCode
