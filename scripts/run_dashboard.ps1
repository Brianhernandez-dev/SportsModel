[CmdletBinding()]
param(
    [ValidateRange(1, 65535)]
    [int]$Port = 8501
)

$ErrorActionPreference = "Stop"

. (Join-Path $PSScriptRoot "dashboard_health.ps1")

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

$repositoryRoot = Split-Path `
    -Parent `
    $PSScriptRoot

$sourcePath = Join-Path `
    $repositoryRoot `
    "src"

$appPath = Join-Path `
    $sourcePath `
    "sportsmodel\dashboard\app.py"

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

    Write-Warning (
        "Stopping proven stale SportsModel dashboard listener " +
        "$($listener.OwningProcess) on port $Port."
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

try {
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

    Write-Host "Owned PID:  $($childProcess.Id)"

    $startupDeadline = [DateTime]::UtcNow.AddSeconds(60)
    $consecutiveHealthFailures = 0

    while (-not $childProcess.WaitForExit(5000)) {
        $health = Get-SportsModelDashboardHealth `
            -Port $Port `
            -TimeoutSeconds 3

        if ($health.Healthy) {
            $consecutiveHealthFailures = 0
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
    $wrapperExitCode = if ($childExitCode -eq 0) { 1 } else { $childExitCode }
}
catch {
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
