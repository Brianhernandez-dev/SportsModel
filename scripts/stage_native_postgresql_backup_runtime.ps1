[CmdletBinding()]
param(
    [ValidateSet("Plan", "Stage")]
    [string]$Action = "Plan",
    [string]$RuntimeDirectory = "D:\SportsModelOps\native_postgresql_backup",
    [string]$ScheduledIdentity = "AI-BETO\Brian",
    [switch]$ApproveProtectedRuntimeStage
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$SourceDirectory = [IO.Path]::GetFullPath($PSScriptRoot)
$RuntimeDirectory = [IO.Path]::GetFullPath($RuntimeDirectory)
$RuntimeFiles = @(
    "run_native_postgresql_backup.ps1",
    "invoke_native_postgresql_backup_restore_acceptance.ps1",
    "wait_for_sportsmodel_database.ps1"
)
$ManifestName = "runtime-manifest.json"
$SystemSid = [Security.Principal.SecurityIdentifier]"S-1-5-18"
$AdministratorsSid = [Security.Principal.SecurityIdentifier]"S-1-5-32-544"
$Allow = [Security.AccessControl.AccessControlType]::Allow
$DirectoryInheritance = (
    [Security.AccessControl.InheritanceFlags]::ContainerInherit -bor
    [Security.AccessControl.InheritanceFlags]::ObjectInherit
)
$NoInheritance = [Security.AccessControl.InheritanceFlags]::None
$NoPropagation = [Security.AccessControl.PropagationFlags]::None

function Resolve-IdentitySid {
    param([Parameter(Mandatory)][string]$Identity)
    return ([Security.Principal.NTAccount]$Identity).Translate(
        [Security.Principal.SecurityIdentifier]
    )
}

function New-ProtectedRuntimeDirectoryAcl {
    param([Parameter(Mandatory)][Security.Principal.SecurityIdentifier]$UserSid)
    $Acl = [Security.AccessControl.DirectorySecurity]::new()
    $Acl.SetOwner($AdministratorsSid)
    $Acl.SetAccessRuleProtection($true, $false)
    $Acl.AddAccessRule([Security.AccessControl.FileSystemAccessRule]::new(
        $UserSid,
        [Security.AccessControl.FileSystemRights]::ReadAndExecute,
        $DirectoryInheritance,
        $NoPropagation,
        $Allow
    ))
    foreach ($Sid in @($SystemSid, $AdministratorsSid)) {
        $Acl.AddAccessRule([Security.AccessControl.FileSystemAccessRule]::new(
            $Sid,
            [Security.AccessControl.FileSystemRights]::FullControl,
            $DirectoryInheritance,
            $NoPropagation,
            $Allow
        ))
    }
    return $Acl
}

function New-ProtectedRuntimeFileAcl {
    param([Parameter(Mandatory)][Security.Principal.SecurityIdentifier]$UserSid)
    $Acl = [Security.AccessControl.FileSecurity]::new()
    $Acl.SetOwner($AdministratorsSid)
    $Acl.SetAccessRuleProtection($true, $false)
    $Acl.AddAccessRule([Security.AccessControl.FileSystemAccessRule]::new(
        $UserSid,
        [Security.AccessControl.FileSystemRights]::ReadAndExecute,
        $Allow
    ))
    foreach ($Sid in @($SystemSid, $AdministratorsSid)) {
        $Acl.AddAccessRule([Security.AccessControl.FileSystemAccessRule]::new(
            $Sid,
            [Security.AccessControl.FileSystemRights]::FullControl,
            $Allow
        ))
    }
    return $Acl
}

function Get-RightsBySid {
    param(
        [Parameter(Mandatory)][Security.AccessControl.FileSystemSecurity]$Acl,
        [Parameter(Mandatory)][string]$Purpose,
        [Parameter(Mandatory)][string[]]$AllowedSids,
        [switch]$RequireExplicit
    )
    $RightsBySid = @{}
    foreach ($Rule in $Acl.GetAccessRules(
        $true,
        $true,
        [Security.Principal.SecurityIdentifier]
    )) {
        $Sid = $Rule.IdentityReference.Value
        if (
            ($RequireExplicit.IsPresent -and $Rule.IsInherited) `
                -or $Rule.AccessControlType -ne $Allow `
                -or $Sid -notin $AllowedSids
        ) {
            throw "$Purpose contains an inherited or unapproved ACL entry."
        }
        if ($RightsBySid.ContainsKey($Sid)) {
            throw "$Purpose contains duplicate ACL entries for an approved identity."
        }
        $RightsBySid[$Sid] = [long]$Rule.FileSystemRights
    }
    return $RightsBySid
}

function Assert-ExactProtectedAcl {
    param(
        [Parameter(Mandatory)][string]$Path,
        [Parameter(Mandatory)][string]$Purpose,
        [Parameter(Mandatory)]
        [Security.Principal.SecurityIdentifier]$UserSid,
        [switch]$Directory
    )
    if ($Directory.IsPresent) {
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
    if (-not $Acl.AreAccessRulesProtected) {
        throw "$Purpose ACL inheritance is not protected."
    }
    $OwnerSid = $Acl.GetOwner([Security.Principal.SecurityIdentifier])
    if ($OwnerSid -ne $AdministratorsSid) {
        throw "$Purpose owner is not BUILTIN\Administrators."
    }
    $AllowedSids = @(
        $UserSid.Value,
        $SystemSid.Value,
        $AdministratorsSid.Value
    )
    $RightsBySid = Get-RightsBySid `
        -Acl $Acl `
        -Purpose $Purpose `
        -AllowedSids $AllowedSids `
        -RequireExplicit
    $ExpectedRights = @{
        $UserSid.Value = (
            [Security.AccessControl.FileSystemRights]::ReadAndExecute -bor
            [Security.AccessControl.FileSystemRights]::Synchronize
        )
        $SystemSid.Value = [Security.AccessControl.FileSystemRights]::FullControl
        $AdministratorsSid.Value = [Security.AccessControl.FileSystemRights]::FullControl
    }
    if ($RightsBySid.Count -ne $ExpectedRights.Count) {
        throw "$Purpose does not contain exactly the approved ACL entries."
    }
    foreach ($Sid in $ExpectedRights.Keys) {
        if (
            -not $RightsBySid.ContainsKey($Sid) `
                -or [long]$RightsBySid[$Sid] -ne [long]$ExpectedRights[$Sid]
        ) {
            throw "$Purpose ACL rights do not match the approved rights."
        }
    }
    foreach ($Rule in $Acl.GetAccessRules(
        $true,
        $false,
        [Security.Principal.SecurityIdentifier]
    )) {
        if ($Directory.IsPresent) {
            if (
                $Rule.InheritanceFlags -ne $DirectoryInheritance `
                    -or $Rule.PropagationFlags -ne $NoPropagation
            ) {
                throw "$Purpose ACL entry does not apply exactly to children."
            }
        }
        elseif (
            $Rule.InheritanceFlags -ne $NoInheritance `
                -or $Rule.PropagationFlags -ne $NoPropagation
        ) {
            throw "$Purpose file ACL contains unexpected inheritance flags."
        }
    }
}

function Assert-SafeRuntimeParent {
    param([Parameter(Mandatory)][string]$Path)
    if (-not (Test-Path -LiteralPath $Path -PathType Container)) {
        throw "The immediate runtime parent must already exist: $Path"
    }
    $Item = Get-Item -LiteralPath $Path -Force
    if (($Item.Attributes -band [IO.FileAttributes]::ReparsePoint) -ne 0) {
        throw "The immediate runtime parent must not be a reparse point."
    }
    $Acl = [IO.Directory]::GetAccessControl($Path)
    $OwnerSid = $Acl.GetOwner([Security.Principal.SecurityIdentifier])
    if ($OwnerSid.Value -notin @($SystemSid.Value, $AdministratorsSid.Value)) {
        throw "The immediate runtime parent has an unapproved owner."
    }
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
    $PrivilegedRights = @{
        $SystemSid.Value = [long]0
        $AdministratorsSid.Value = [long]0
    }
    foreach ($Rule in $Acl.GetAccessRules(
        $true,
        $true,
        [Security.Principal.SecurityIdentifier]
    )) {
        $Sid = $Rule.IdentityReference.Value
        if ($Rule.AccessControlType -ne $Allow) {
            throw "The immediate runtime parent contains an unapproved deny ACL entry."
        }
        if (
            $Sid -notin @($SystemSid.Value, $AdministratorsSid.Value) `
                -and ([long]$Rule.FileSystemRights -band [long]$WriteRights) -ne 0
        ) {
            throw (
                "The immediate runtime parent grants an unapproved identity " +
                "write, delete, or permission-management rights."
            )
        }
        if ($PrivilegedRights.ContainsKey($Sid)) {
            $PrivilegedRights[$Sid] = (
                [long]$PrivilegedRights[$Sid] -bor [long]$Rule.FileSystemRights
            )
        }
    }
    foreach ($Sid in $PrivilegedRights.Keys) {
        $FullControl = [long][Security.AccessControl.FileSystemRights]::FullControl
        if (($PrivilegedRights[$Sid] -band $FullControl) -ne $FullControl) {
            throw (
                "The immediate runtime parent does not grant SYSTEM and " +
                "Administrators Full Control."
            )
        }
    }
}

foreach ($Name in $RuntimeFiles) {
    $SourcePath = Join-Path $SourceDirectory $Name
    if (-not (Test-Path -LiteralPath $SourcePath -PathType Leaf)) {
        throw "Required runtime source file was not found: $SourcePath"
    }
}

if ($Action -eq "Plan") {
    Write-Host "PLAN ONLY - no runtime files or ACLs were changed."
    Write-Host "Runtime directory: $RuntimeDirectory"
    Write-Host "Scheduled identity: $ScheduledIdentity (ReadAndExecute only)"
    Write-Host "Owner: BUILTIN\Administrators"
    Write-Host "Runtime files: $($RuntimeFiles -join ', ')"
    Write-Host "The immediate runtime parent must already exist and be non-writable."
    Write-Host (
        "Credential file config\backup.env is provisioned separately and " +
        "is never copied by this staging helper."
    )
    return
}

if (-not $ApproveProtectedRuntimeStage.IsPresent) {
    throw (
        "Protected runtime staging was refused. Supply " +
        "-ApproveProtectedRuntimeStage only after that exact deployment " +
        "phase is approved."
    )
}
if (Test-Path -LiteralPath $RuntimeDirectory) {
    throw "Runtime target already exists; overwrite is refused."
}

$UserSid = Resolve-IdentitySid -Identity $ScheduledIdentity
$RuntimeParent = Split-Path -Parent $RuntimeDirectory
Assert-SafeRuntimeParent -Path $RuntimeParent

# Establish and verify the trust boundary before any executable content exists.
$null = New-Item -ItemType Directory -Path $RuntimeDirectory
[IO.Directory]::SetAccessControl(
    $RuntimeDirectory,
    (New-ProtectedRuntimeDirectoryAcl -UserSid $UserSid)
)
Assert-ExactProtectedAcl `
    -Path $RuntimeDirectory `
    -Purpose "Protected runtime" `
    -UserSid $UserSid `
    -Directory

$ConfigDirectory = Join-Path $RuntimeDirectory "config"
$null = New-Item -ItemType Directory -Path $ConfigDirectory
[IO.Directory]::SetAccessControl(
    $ConfigDirectory,
    (New-ProtectedRuntimeDirectoryAcl -UserSid $UserSid)
)
Assert-ExactProtectedAcl `
    -Path $ConfigDirectory `
    -Purpose "Protected runtime config" `
    -UserSid $UserSid `
    -Directory

foreach ($Name in $RuntimeFiles) {
    $Path = Join-Path $RuntimeDirectory $Name
    Copy-Item `
        -LiteralPath (Join-Path $SourceDirectory $Name) `
        -Destination $Path
    [IO.File]::SetAccessControl(
        $Path,
        (New-ProtectedRuntimeFileAcl -UserSid $UserSid)
    )
}

# Validate every final file ACL before any hash can certify its content.
foreach ($Name in $RuntimeFiles) {
    Assert-ExactProtectedAcl `
        -Path (Join-Path $RuntimeDirectory $Name) `
        -Purpose "Runtime $Name" `
        -UserSid $UserSid
}
$ManifestFiles = @(
    foreach ($Name in $RuntimeFiles) {
        $Path = Join-Path $RuntimeDirectory $Name
        [pscustomobject][ordered]@{
            Name = $Name
            Sha256 = (Get-FileHash -LiteralPath $Path -Algorithm SHA256).Hash
        }
    }
)
$Manifest = [pscustomobject][ordered]@{
    FormatVersion = 1
    Files = $ManifestFiles
}
$ManifestPath = Join-Path $RuntimeDirectory $ManifestName
$Manifest | ConvertTo-Json -Depth 4 |
    Set-Content -LiteralPath $ManifestPath -Encoding utf8
[IO.File]::SetAccessControl(
    $ManifestPath,
    (New-ProtectedRuntimeFileAcl -UserSid $UserSid)
)
Assert-ExactProtectedAcl `
    -Path $ManifestPath `
    -Purpose "Protected runtime manifest" `
    -UserSid $UserSid

# A final complete validation catches any substitution before successful return.
Assert-ExactProtectedAcl `
    -Path $RuntimeDirectory `
    -Purpose "Protected runtime" `
    -UserSid $UserSid `
    -Directory
Assert-ExactProtectedAcl `
    -Path $ConfigDirectory `
    -Purpose "Protected runtime config" `
    -UserSid $UserSid `
    -Directory
foreach ($Name in $RuntimeFiles) {
    Assert-ExactProtectedAcl `
        -Path (Join-Path $RuntimeDirectory $Name) `
        -Purpose "Runtime $Name" `
        -UserSid $UserSid
}

Write-Host "Protected runtime staged. No credential was copied."
