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

$RuntimeDirectory = [IO.Path]::GetFullPath($PSScriptRoot)
$ProtectedStorageRoot = "D:\SportsModelBackups\PostgreSQL"
$RuntimeManifestName = "runtime-manifest.json"
$RequiredRuntimeFiles = @(
    "run_native_postgresql_backup.ps1",
    "invoke_native_postgresql_backup_restore_acceptance.ps1",
    "wait_for_sportsmodel_database.ps1"
)
$CredentialNames = @(
    "POSTGRES_HOST",
    "POSTGRES_PORT",
    "POSTGRES_DB",
    "POSTGRES_USER",
    "POSTGRES_PASSWORD"
)
$BackupFilePattern = (
    "^sportsmodel-native-(?<stamp>[0-9]{8}t[0-9]{6}z)\.dump$"
)
$ManifestFilePattern = (
    "^sportsmodel-native-(?<stamp>[0-9]{8}t[0-9]{6}z)" +
    "\.dump\.manifest\.json$"
)

function Assert-ProtectedArtifactDirectory {
    param(
        [Parameter(Mandatory)]
        [string]$Path,

        [Parameter(Mandatory)]
        [string]$Purpose
    )

    if (-not (Test-Path -LiteralPath $Path -PathType Container)) {
        throw (
            "$Purpose directory must already exist with its approved " +
            "protected ACL."
        )
    }

    $Acl = [IO.Directory]::GetAccessControl($Path)
    $CurrentSid = [Security.Principal.WindowsIdentity]::GetCurrent().User
    $OwnerSid = $Acl.GetOwner(
        [Security.Principal.SecurityIdentifier]
    )
    if ($OwnerSid -ne $CurrentSid) {
        throw "$Purpose directory owner is not the scheduled identity."
    }
    if (-not $Acl.AreAccessRulesProtected) {
        throw "$Purpose directory ACL inheritance is not protected."
    }

    $SystemSid = [Security.Principal.SecurityIdentifier]"S-1-5-18"
    $AdministratorsSid = (
        [Security.Principal.SecurityIdentifier]"S-1-5-32-544"
    )
    $AllowedSids = @(
        $CurrentSid.Value,
        $SystemSid.Value,
        $AdministratorsSid.Value
    )
    $RightsBySid = @{}
    foreach (
        $Rule in $Acl.GetAccessRules(
            $true,
            $true,
            [Security.Principal.SecurityIdentifier]
        )
    ) {
        $RuleSid = $Rule.IdentityReference.Value
        if (
            $Rule.IsInherited `
                -or $Rule.AccessControlType -ne (
                    [Security.AccessControl.AccessControlType]::Allow
                ) `
                -or $RuleSid -notin $AllowedSids
        ) {
            throw "$Purpose directory contains an unapproved ACL entry."
        }

        $RequiredInheritance = (
            [Security.AccessControl.InheritanceFlags]::ContainerInherit -bor
            [Security.AccessControl.InheritanceFlags]::ObjectInherit
        )
        if (
            ($Rule.InheritanceFlags -band $RequiredInheritance) -ne
            $RequiredInheritance `
                -or $Rule.PropagationFlags -ne (
                    [Security.AccessControl.PropagationFlags]::None
                )
        ) {
            throw "$Purpose directory ACL entries must apply to children."
        }

        if (-not $RightsBySid.ContainsKey($RuleSid)) {
            $RightsBySid[$RuleSid] = [long]0
        }
        $RightsBySid[$RuleSid] = (
            [long]$RightsBySid[$RuleSid] -bor [long]$Rule.FileSystemRights
        )
    }

    $RequiredRights = @{
        $CurrentSid.Value = [Security.AccessControl.FileSystemRights]::Modify
        $SystemSid.Value = [Security.AccessControl.FileSystemRights]::FullControl
        $AdministratorsSid.Value = (
            [Security.AccessControl.FileSystemRights]::FullControl
        )
    }
    foreach ($Sid in $RequiredRights.Keys) {
        $Required = [long]$RequiredRights[$Sid]
        if (
            -not $RightsBySid.ContainsKey($Sid) `
                -or ([long]$RightsBySid[$Sid] -band $Required) -ne $Required
        ) {
            throw "$Purpose directory lacks an approved required ACL entry."
        }
    }

    $ScheduledRights = [long]$RightsBySid[$CurrentSid.Value]
    $PermissionManagementRights = (
        [Security.AccessControl.FileSystemRights]::ChangePermissions -bor
        [Security.AccessControl.FileSystemRights]::TakeOwnership
    )
    if (
        ($ScheduledRights -band [long]$PermissionManagementRights) -ne 0
    ) {
        throw (
            "$Purpose directory grants the scheduled identity " +
            "permission-management rights."
        )
    }
}

function Get-AclRightsBySid {
    param(
        [Parameter(Mandatory)]
        [Security.AccessControl.FileSystemSecurity]$Acl,

        [Parameter(Mandatory)]
        [string[]]$AllowedSids,

        [Parameter(Mandatory)]
        [string]$Purpose,

        [bool]$RequireExplicitRules = $false
    )

    $RightsBySid = @{}
    foreach (
        $Rule in $Acl.GetAccessRules(
            $true,
            $true,
            [Security.Principal.SecurityIdentifier]
        )
    ) {
        $RuleSid = $Rule.IdentityReference.Value
        if (
            ($RequireExplicitRules -and $Rule.IsInherited) `
                -or $Rule.AccessControlType -ne (
                    [Security.AccessControl.AccessControlType]::Allow
                ) `
                -or $RuleSid -notin $AllowedSids
        ) {
            throw "$Purpose contains an unapproved ACL entry."
        }

        if (-not $RightsBySid.ContainsKey($RuleSid)) {
            $RightsBySid[$RuleSid] = [long]0
        }
        $RightsBySid[$RuleSid] = (
            [long]$RightsBySid[$RuleSid] -bor [long]$Rule.FileSystemRights
        )
    }

    return $RightsBySid
}

function Assert-RequiredRights {
    param(
        [Parameter(Mandatory)]
        [hashtable]$RightsBySid,

        [Parameter(Mandatory)]
        [hashtable]$RequiredRights,

        [Parameter(Mandatory)]
        [string]$Purpose
    )

    foreach ($Sid in $RequiredRights.Keys) {
        $Required = [long]$RequiredRights[$Sid]
        if (
            -not $RightsBySid.ContainsKey($Sid) `
                -or ([long]$RightsBySid[$Sid] -band $Required) -ne $Required
        ) {
            throw "$Purpose lacks an approved required ACL entry."
        }
    }
}

function Assert-NoWriteRights {
    param(
        [Parameter(Mandatory)]
        [long]$Rights,

        [Parameter(Mandatory)]
        [string]$Purpose
    )

    $WriteRights = (
        [Security.AccessControl.FileSystemRights]::WriteData -bor
        [Security.AccessControl.FileSystemRights]::AppendData -bor
        [Security.AccessControl.FileSystemRights]::WriteExtendedAttributes -bor
        [Security.AccessControl.FileSystemRights]::WriteAttributes -bor
        [Security.AccessControl.FileSystemRights]::Delete -bor
        [Security.AccessControl.FileSystemRights]::DeleteSubdirectoriesAndFiles -bor
        [Security.AccessControl.FileSystemRights]::ChangePermissions -bor
        [Security.AccessControl.FileSystemRights]::TakeOwnership
    )
    if (($Rights -band [long]$WriteRights) -ne 0) {
        throw "$Purpose grants write or permission-management rights."
    }
}

function Get-ProtectedRuntimeAclContext {
    $CurrentSid = [Security.Principal.WindowsIdentity]::GetCurrent().User
    $SystemSid = [Security.Principal.SecurityIdentifier]"S-1-5-18"
    $AdministratorsSid = (
        [Security.Principal.SecurityIdentifier]"S-1-5-32-544"
    )
    return [pscustomobject]@{
        CurrentSid = $CurrentSid
        SystemSid = $SystemSid
        AdministratorsSid = $AdministratorsSid
        AllowedSids = @(
            $CurrentSid.Value,
            $SystemSid.Value,
            $AdministratorsSid.Value
        )
    }
}

function Assert-ProtectedRuntimePath {
    param(
        [Parameter(Mandatory)]
        [string]$Path,

        [Parameter(Mandatory)]
        [string]$Purpose,

        [bool]$IsDirectory = $false,

        [bool]$CredentialFile = $false
    )

    $Context = Get-ProtectedRuntimeAclContext
    if ($IsDirectory) {
        if (-not (Test-Path -LiteralPath $Path -PathType Container)) {
            throw "$Purpose directory was not found."
        }
        $Acl = [IO.Directory]::GetAccessControl($Path)
    }
    else {
        if (-not (Test-Path -LiteralPath $Path -PathType Leaf)) {
            throw "$Purpose file was not found."
        }
        $Acl = [IO.File]::GetAccessControl($Path)
    }

    $OwnerSid = $Acl.GetOwner(
        [Security.Principal.SecurityIdentifier]
    )
    if (
        $OwnerSid -ne $Context.AdministratorsSid `
            -and $OwnerSid -ne $Context.SystemSid
    ) {
        throw "$Purpose owner is not Administrators or SYSTEM."
    }
    if ($IsDirectory -or $CredentialFile) {
        if (-not $Acl.AreAccessRulesProtected) {
            throw "$Purpose ACL inheritance is not protected."
        }
    }

    $RightsBySid = Get-AclRightsBySid `
        -Acl $Acl `
        -AllowedSids $Context.AllowedSids `
        -Purpose $Purpose `
        -RequireExplicitRules:($IsDirectory -or $CredentialFile)

    if ($CredentialFile) {
        $CurrentRequired = [Security.AccessControl.FileSystemRights]::Read
    }
    else {
        $CurrentRequired = (
            [Security.AccessControl.FileSystemRights]::ReadAndExecute
        )
    }
    Assert-RequiredRights `
        -RightsBySid $RightsBySid `
        -RequiredRights @{
            $Context.CurrentSid.Value = $CurrentRequired
            $Context.SystemSid.Value = (
                [Security.AccessControl.FileSystemRights]::FullControl
            )
            $Context.AdministratorsSid.Value = (
                [Security.AccessControl.FileSystemRights]::FullControl
            )
        } `
        -Purpose $Purpose
    Assert-NoWriteRights `
        -Rights ([long]$RightsBySid[$Context.CurrentSid.Value]) `
        -Purpose $Purpose

    if ($IsDirectory) {
        $RequiredInheritance = (
            [Security.AccessControl.InheritanceFlags]::ContainerInherit -bor
            [Security.AccessControl.InheritanceFlags]::ObjectInherit
        )
        foreach (
            $Rule in $Acl.GetAccessRules(
                $true,
                $false,
                [Security.Principal.SecurityIdentifier]
            )
        ) {
            if (
                ($Rule.InheritanceFlags -band $RequiredInheritance) -ne
                $RequiredInheritance `
                    -or $Rule.PropagationFlags -ne (
                        [Security.AccessControl.PropagationFlags]::None
                    )
            ) {
                throw "$Purpose ACL entries must apply to children."
            }
        }
    }
}

function Assert-ProtectedRuntime {
    Assert-ProtectedRuntimePath `
        -Path $RuntimeDirectory `
        -Purpose "Protected runtime" `
        -IsDirectory $true

    Assert-ProtectedRuntimePath `
        -Path (Join-Path $RuntimeDirectory "config") `
        -Purpose "Protected runtime config" `
        -IsDirectory $true

    $ExpectedTopLevelFiles = @(
        $RequiredRuntimeFiles + $RuntimeManifestName
    )
    $UnexpectedFiles = @(
        Get-ChildItem -LiteralPath $RuntimeDirectory -File |
            Where-Object { $_.Name -notin $ExpectedTopLevelFiles }
    )
    if ($UnexpectedFiles.Count -gt 0) {
        throw "Protected runtime contains an unexpected top-level file."
    }
    $UnexpectedDirectories = @(
        Get-ChildItem -LiteralPath $RuntimeDirectory -Directory -Force |
            Where-Object { $_.Name -cne "config" }
    )
    if ($UnexpectedDirectories.Count -gt 0) {
        throw "Protected runtime contains an unexpected directory."
    }

    $ConfigDirectory = Join-Path $RuntimeDirectory "config"
    $UnexpectedConfigEntries = @(
        Get-ChildItem -LiteralPath $ConfigDirectory -Force |
            Where-Object {
                $_.PSIsContainer -or $_.Name -cne "backup.env"
            }
    )
    if ($UnexpectedConfigEntries.Count -gt 0) {
        throw "Protected runtime config contains an unexpected entry."
    }

    $ManifestPath = Join-Path $RuntimeDirectory $RuntimeManifestName
    Assert-ProtectedRuntimePath `
        -Path $ManifestPath `
        -Purpose "Protected runtime manifest"
    $Manifest = Get-Content -LiteralPath $ManifestPath -Raw |
        ConvertFrom-Json
    if ($Manifest.FormatVersion -ne 1) {
        throw "Protected runtime manifest format is unsupported."
    }
    $ManifestFiles = @($Manifest.Files)
    if ($ManifestFiles.Count -ne $RequiredRuntimeFiles.Count) {
        throw "Protected runtime manifest file set is incomplete."
    }
    foreach ($Name in $RequiredRuntimeFiles) {
        $Path = Join-Path $RuntimeDirectory $Name
        Assert-ProtectedRuntimePath -Path $Path -Purpose "Runtime $Name"
        $Entries = @($ManifestFiles | Where-Object { $_.Name -ceq $Name })
        if ($Entries.Count -ne 1) {
            throw "Protected runtime manifest does not uniquely name $Name."
        }
        $ActualHash = (Get-FileHash -LiteralPath $Path -Algorithm SHA256).Hash
        if ($ActualHash -cne $Entries[0].Sha256) {
            throw "Protected runtime hash verification failed for $Name."
        }
    }
}

function Assert-ProtectedCredentialFile {
    param([Parameter(Mandatory)][string]$Path)

    Assert-ProtectedRuntimePath `
        -Path $Path `
        -Purpose "Backup credential" `
        -CredentialFile $true

    $Observed = @{}
    foreach ($Line in Get-Content -LiteralPath $Path) {
        $Trimmed = $Line.Trim()
        if (
            [string]::IsNullOrWhiteSpace($Trimmed) `
                -or $Trimmed.StartsWith("#")
        ) {
            continue
        }
        $Parts = $Trimmed.Split(@("="), 2, [StringSplitOptions]::None)
        if ($Parts.Count -ne 2) {
            throw "Backup credential file contains a malformed entry."
        }
        $Name = $Parts[0].Trim()
        if ($Name -notin $CredentialNames) {
            throw "Backup credential file contains an unexpected key."
        }
        if ($Observed.ContainsKey($Name)) {
            throw "Backup credential file contains a duplicate key."
        }
        if ([string]::IsNullOrWhiteSpace($Parts[1])) {
            throw "Backup credential file contains an empty required value."
        }
        $Observed[$Name] = $true
    }
    foreach ($Name in $CredentialNames) {
        if (-not $Observed.ContainsKey($Name)) {
            throw "Backup credential file is missing required key $Name."
        }
    }
}

if ([string]::IsNullOrWhiteSpace($BackupDirectory)) {
    $BackupDirectory = Join-Path $ProtectedStorageRoot "backups"
}
if ([string]::IsNullOrWhiteSpace($LogDirectory)) {
    $LogDirectory = Join-Path $ProtectedStorageRoot "logs"
}
if ([string]::IsNullOrWhiteSpace($EnvironmentPath)) {
    $EnvironmentPath = Join-Path $RuntimeDirectory "config\backup.env"
}
if ([string]::IsNullOrWhiteSpace($AcceptanceToolPath)) {
    $AcceptanceToolPath = Join-Path `
        $RuntimeDirectory `
        "invoke_native_postgresql_backup_restore_acceptance.ps1"
}

$BackupDirectory = [IO.Path]::GetFullPath($BackupDirectory)
$LogDirectory = [IO.Path]::GetFullPath($LogDirectory)
$EnvironmentPath = [IO.Path]::GetFullPath($EnvironmentPath)
$AcceptanceToolPath = [IO.Path]::GetFullPath($AcceptanceToolPath)

if ($RuntimeDirectory -cne [IO.Path]::GetFullPath($PSScriptRoot)) {
    throw "The backup wrapper must execute from its protected runtime."
}
$ExpectedAcceptanceToolPath = Join-Path `
    $RuntimeDirectory `
    "invoke_native_postgresql_backup_restore_acceptance.ps1"
if ($AcceptanceToolPath -cne $ExpectedAcceptanceToolPath) {
    throw (
        "AcceptanceToolPath must identify the engine inside the protected " +
        "runtime."
    )
}
$ExpectedEnvironmentPath = Join-Path $RuntimeDirectory "config\backup.env"
if ($EnvironmentPath -cne $ExpectedEnvironmentPath) {
    throw "EnvironmentPath must identify protected config\backup.env."
}

Assert-ProtectedRuntime
Assert-ProtectedCredentialFile -Path $EnvironmentPath

Assert-ProtectedArtifactDirectory `
    -Path $BackupDirectory `
    -Purpose "Backup"
Assert-ProtectedArtifactDirectory `
    -Path $LogDirectory `
    -Purpose "Log"

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

    $CurrentPairs = @(
        $Pairs | Where-Object { $_.BackupPath -ceq $CurrentBackupPath }
    )
    if ($CurrentPairs.Count -ne 1) {
        throw "Retention could not uniquely identify the current backup pair."
    }

    $RetainedPaths = @{}
    $RetainedPaths[$CurrentPairs[0].BackupPath] = $true
    $AdditionalRetentionCount = $RetentionCount - 1
    if ($AdditionalRetentionCount -gt 0) {
        $Pairs |
            Where-Object { $_.BackupPath -cne $CurrentBackupPath } |
            Select-Object -First $AdditionalRetentionCount |
            ForEach-Object { $RetainedPaths[$_.BackupPath] = $true }
    }
    $ExpiredPairs = @(
        $Pairs | Where-Object { -not $RetainedPaths.ContainsKey($_.BackupPath) }
    )
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
    $BackupDirectory `
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
