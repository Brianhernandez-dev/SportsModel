[CmdletBinding()]
param(
    [string]$BackupDirectory,

    [string]$LogDirectory,

    [string]$EnvironmentPath,

    [string]$AcceptanceToolPath,

    [ValidateRange(1, 1000)]
    [int]$RetentionCount = 30,

    [DateTimeOffset]$UtcNow = [DateTimeOffset]::UtcNow
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$RepositoryRoot = Split-Path -Parent $PSScriptRoot
$BackupFilePattern = (
    "^sportsmodel-native-(?<stamp>[0-9]{8}t[0-9]{6}z)\.dump$"
)
$ManifestFilePattern = (
    "^sportsmodel-native-(?<stamp>[0-9]{8}t[0-9]{6}z)" +
    "\.dump\.manifest\.json$"
)

if ([string]::IsNullOrWhiteSpace($BackupDirectory)) {
    $BackupDirectory = Join-Path $RepositoryRoot "backups\postgresql"
}
if ([string]::IsNullOrWhiteSpace($LogDirectory)) {
    $LogDirectory = Join-Path $RepositoryRoot "logs\postgresql_backup"
}
if ([string]::IsNullOrWhiteSpace($EnvironmentPath)) {
    $EnvironmentPath = Join-Path $RepositoryRoot ".env"
}
if ([string]::IsNullOrWhiteSpace($AcceptanceToolPath)) {
    $AcceptanceToolPath = Join-Path `
        $PSScriptRoot `
        "invoke_native_postgresql_backup_restore_acceptance.ps1"
}

$BackupDirectory = [IO.Path]::GetFullPath($BackupDirectory)
$LogDirectory = [IO.Path]::GetFullPath($LogDirectory)
$EnvironmentPath = [IO.Path]::GetFullPath($EnvironmentPath)
$AcceptanceToolPath = [IO.Path]::GetFullPath($AcceptanceToolPath)

if (
    [IO.Path]::GetFileName($AcceptanceToolPath) -cne
    "invoke_native_postgresql_backup_restore_acceptance.ps1"
) {
    throw (
        "AcceptanceToolPath must identify " +
        "invoke_native_postgresql_backup_restore_acceptance.ps1."
    )
}
if (-not (Test-Path -LiteralPath $AcceptanceToolPath -PathType Leaf)) {
    throw "The accepted backup engine was not found."
}
if (-not (Test-Path -LiteralPath $EnvironmentPath -PathType Leaf)) {
    throw "The production environment file was not found."
}

$null = New-Item `
    -ItemType Directory `
    -Path $BackupDirectory `
    -Force
$null = New-Item `
    -ItemType Directory `
    -Path $LogDirectory `
    -Force

$AttemptStamp = $UtcNow.ToUniversalTime().ToString(
    "yyyyMMdd'T'HHmmss.fffffff'Z'"
)
$AttemptNonce = [Guid]::NewGuid().ToString("N")
$AttemptId = "$AttemptStamp-pid$PID-$AttemptNonce"
$LogPath = Join-Path `
    $LogDirectory `
    "postgresql_backup_$AttemptId.log"

$LogStream = [IO.File]::Open(
    $LogPath,
    [IO.FileMode]::CreateNew,
    [IO.FileAccess]::Write,
    [IO.FileShare]::Read
)
$LogStream.Close()

function Write-BackupLog {
    param(
        [Parameter(Mandatory)]
        [string]$Message
    )

    $Timestamp = [DateTimeOffset]::UtcNow.ToString("o")
    $Line = "[$Timestamp] attempt=$AttemptId $Message"
    Add-Content `
        -LiteralPath $LogPath `
        -Value $Line `
        -Encoding UTF8
    Write-Host $Line
}


function Invoke-AcceptedBackupAction {
    param(
        [Parameter(Mandatory)]
        [ValidateSet("Backup", "VerifyBackup")]
        [string]$Action,

        [Parameter(Mandatory)]
        [string]$ArtifactPath,

        [Parameter(Mandatory)]
        [string]$ArtifactManifestPath
    )

    $PowerShellPath = Join-Path $PSHOME "powershell.exe"
    if (-not (Test-Path -LiteralPath $PowerShellPath -PathType Leaf)) {
        $PowerShellPath = (
            Get-Command powershell.exe -ErrorAction Stop
        ).Source
    }

    $Arguments = @(
        "-NoProfile",
        "-NonInteractive",
        "-ExecutionPolicy",
        "Bypass",
        "-File",
        $AcceptanceToolPath,
        "-Action",
        $Action,
        "-EnvironmentPath",
        $EnvironmentPath,
        "-BackupPath",
        $ArtifactPath,
        "-ManifestPath",
        $ArtifactManifestPath
    )
    if ($Action -eq "Backup") {
        $Arguments += "-ApproveProductionBackup"
    }

    $Output = @(& $PowerShellPath @Arguments 2>&1)
    $ExitCode = $LASTEXITCODE
    if ($ExitCode -ne 0) {
        throw [InvalidOperationException]::new(
            "Accepted backup engine action $Action failed with exit code " +
            "$ExitCode."
        )
    }

    return $Output
}


function Get-VerifiedBackupPairs {
    $ManagedFiles = @(
        Get-ChildItem `
            -LiteralPath $BackupDirectory `
            -File |
            Where-Object { $_.Name -like "sportsmodel-native-*" }
    )

    $MalformedFiles = @(
        $ManagedFiles |
            Where-Object {
                $_.Name -cnotmatch $BackupFilePattern `
                    -and $_.Name -cnotmatch $ManifestFilePattern
            }
    )
    if ($MalformedFiles.Count -gt 0) {
        throw (
            "Retention refused because malformed managed backup artifacts " +
            "were found. No retention deletion was attempted."
        )
    }

    $DumpFiles = @(
        $ManagedFiles |
            Where-Object { $_.Name -cmatch $BackupFilePattern }
    )
    $ManifestFiles = @(
        $ManagedFiles |
            Where-Object { $_.Name -cmatch $ManifestFilePattern }
    )

    $Pairs = @()
    foreach ($DumpFile in $DumpFiles) {
        $ManifestFilePath = "$($DumpFile.FullName).manifest.json"
        if (-not (Test-Path -LiteralPath $ManifestFilePath -PathType Leaf)) {
            throw (
                "Retention refused because an unpaired backup artifact " +
                "was found. No retention deletion was attempted."
            )
        }

        if ($DumpFile.Name -cnotmatch $BackupFilePattern) {
            throw "Internal backup-name validation failed."
        }
        $Stamp = [DateTimeOffset]::ParseExact(
            $Matches["stamp"],
            "yyyyMMdd't'HHmmss'z'",
            [Globalization.CultureInfo]::InvariantCulture,
            [Globalization.DateTimeStyles]::AssumeUniversal
        ).ToUniversalTime()

        $Pairs += [pscustomobject]@{
            Stamp = $Stamp
            BackupPath = $DumpFile.FullName
            ManifestPath = $ManifestFilePath
        }
    }

    foreach ($ManifestFile in $ManifestFiles) {
        $ExpectedDumpPath = $ManifestFile.FullName.Substring(
            0,
            $ManifestFile.FullName.Length - ".manifest.json".Length
        )
        if (-not (Test-Path -LiteralPath $ExpectedDumpPath -PathType Leaf)) {
            throw (
                "Retention refused because an unpaired backup manifest " +
                "was found. No retention deletion was attempted."
            )
        }
    }

    return @($Pairs | Sort-Object Stamp -Descending)
}


function Invoke-VerifiedPairRetention {
    param(
        [Parameter(Mandatory)]
        [string]$CurrentBackupPath
    )

    $Pairs = @(Get-VerifiedBackupPairs)

    foreach ($Pair in $Pairs) {
        if ($Pair.BackupPath -ceq $CurrentBackupPath) {
            continue
        }

        $null = Invoke-AcceptedBackupAction `
            -Action "VerifyBackup" `
            -ArtifactPath $Pair.BackupPath `
            -ArtifactManifestPath $Pair.ManifestPath
    }

    $ExpiredPairs = @($Pairs | Select-Object -Skip $RetentionCount)
    foreach ($Pair in $ExpiredPairs) {
        Remove-Item `
            -LiteralPath $Pair.BackupPath `
            -Force `
            -ErrorAction Stop
        Remove-Item `
            -LiteralPath $Pair.ManifestPath `
            -Force `
            -ErrorAction Stop
    }

    Write-BackupLog (
        "Retention completed. Verified pairs=$($Pairs.Count); " +
        "retained=$([Math]::Min($Pairs.Count, $RetentionCount)); " +
        "deleted=$($ExpiredPairs.Count)."
    )
}


$BackupStamp = $UtcNow.ToUniversalTime().ToString(
    "yyyyMMdd't'HHmmss'z'"
)
$BackupPath = Join-Path `
    $BackupDirectory `
    "sportsmodel-native-$BackupStamp.dump"
$ManifestPath = "$BackupPath.manifest.json"
$LockPath = Join-Path `
    $LogDirectory `
    "run_native_postgresql_backup.lock"

$LockStream = $null
$Stage = "initialization"
$ExitCode = 1

try {
    Write-BackupLog "Backup wrapper started."

    $Stage = "overlap-protection"
    try {
        $LockStream = [IO.File]::Open(
            $LockPath,
            [IO.FileMode]::OpenOrCreate,
            [IO.FileAccess]::ReadWrite,
            [IO.FileShare]::None
        )
    }
    catch [IO.IOException] {
        throw [InvalidOperationException]::new(
            "Another SportsModel native PostgreSQL backup wrapper is active."
        )
    }
    Write-BackupLog "Exclusive backup-wrapper lock acquired."

    $Stage = "artifact-preflight"
    if (
        (Test-Path -LiteralPath $BackupPath) `
        -or (Test-Path -LiteralPath $ManifestPath)
    ) {
        throw [InvalidOperationException]::new(
            "Timestamped backup artifact already exists; overwrite refused."
        )
    }
    Write-BackupLog (
        "Backup artifact selected. File=$([IO.Path]::GetFileName($BackupPath))."
    )

    $Stage = "backup"
    Write-BackupLog "Accepted backup engine action Backup started."
    $null = Invoke-AcceptedBackupAction `
        -Action "Backup" `
        -ArtifactPath $BackupPath `
        -ArtifactManifestPath $ManifestPath
    Write-BackupLog "Accepted backup engine action Backup completed."

    $Stage = "verification"
    Write-BackupLog "Accepted backup engine action VerifyBackup started."
    $null = Invoke-AcceptedBackupAction `
        -Action "VerifyBackup" `
        -ArtifactPath $BackupPath `
        -ArtifactManifestPath $ManifestPath
    Write-BackupLog "Accepted backup engine action VerifyBackup completed."

    $Stage = "retention"
    Invoke-VerifiedPairRetention -CurrentBackupPath $BackupPath

    $Stage = "complete"
    Write-BackupLog (
        "FINAL SUCCESS. Backup and manifest were created, verified, and " +
        "retention completed."
    )
    $ExitCode = 0
}
catch {
    try {
        Write-BackupLog (
            "FINAL FAILURE. Stage=$Stage; " +
            "error_type=$($_.Exception.GetType().FullName)."
        )
    }
    catch {
        # The task still fails nonzero if durable logging itself is unavailable.
    }

    Write-Error `
        -ErrorAction Continue `
        "SportsModel native PostgreSQL backup failed. Stage=$Stage. " +
        "Review the durable wrapper log."
    $ExitCode = 1
}
finally {
    if ($null -ne $LockStream) {
        $LockStream.Dispose()
    }
}

exit $ExitCode
