[CmdletBinding()]
param(
    [ValidateSet("Plan", "Stage")]
    [string]$Action = "Plan",

    [string]$RuntimeDirectory = (
        "D:\SportsModelOps\native_postgresql_backup"
    ),

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

function Resolve-IdentitySid {
    param([Parameter(Mandatory)][string]$Identity)

    return ([Security.Principal.NTAccount]$Identity).Translate(
        [Security.Principal.SecurityIdentifier]
    )
}

function New-ProtectedRuntimeAcl {
    param([Parameter(Mandatory)][Security.Principal.SecurityIdentifier]$UserSid)

    $SystemSid = [Security.Principal.SecurityIdentifier]"S-1-5-18"
    $AdministratorsSid = (
        [Security.Principal.SecurityIdentifier]"S-1-5-32-544"
    )
    $Inheritance = (
        [Security.AccessControl.InheritanceFlags]::ContainerInherit -bor
        [Security.AccessControl.InheritanceFlags]::ObjectInherit
    )
    $Propagation = [Security.AccessControl.PropagationFlags]::None
    $Allow = [Security.AccessControl.AccessControlType]::Allow
    $Acl = [Security.AccessControl.DirectorySecurity]::new()
    $Acl.SetOwner($AdministratorsSid)
    $Acl.SetAccessRuleProtection($true, $false)
    $Acl.AddAccessRule([Security.AccessControl.FileSystemAccessRule]::new(
        $UserSid,
        [Security.AccessControl.FileSystemRights]::ReadAndExecute,
        $Inheritance,
        $Propagation,
        $Allow
    ))
    foreach ($Sid in @($SystemSid, $AdministratorsSid)) {
        $Acl.AddAccessRule([Security.AccessControl.FileSystemAccessRule]::new(
            $Sid,
            [Security.AccessControl.FileSystemRights]::FullControl,
            $Inheritance,
            $Propagation,
            $Allow
        ))
    }
    return $Acl
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
$null = New-Item -ItemType Directory -Path $RuntimeDirectory
$null = New-Item `
    -ItemType Directory `
    -Path (Join-Path $RuntimeDirectory "config")

foreach ($Name in $RuntimeFiles) {
    Copy-Item `
        -LiteralPath (Join-Path $SourceDirectory $Name) `
        -Destination (Join-Path $RuntimeDirectory $Name)
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
$Manifest | ConvertTo-Json -Depth 4 |
    Set-Content `
        -LiteralPath (Join-Path $RuntimeDirectory $ManifestName) `
        -Encoding utf8

$RuntimeAcl = New-ProtectedRuntimeAcl -UserSid $UserSid
[IO.Directory]::SetAccessControl($RuntimeDirectory, $RuntimeAcl)
$ConfigAcl = New-ProtectedRuntimeAcl -UserSid $UserSid
[IO.Directory]::SetAccessControl(
    (Join-Path $RuntimeDirectory "config"),
    $ConfigAcl
)
foreach ($Path in @(
    $RuntimeFiles | ForEach-Object { Join-Path $RuntimeDirectory $_ }
) + (Join-Path $RuntimeDirectory $ManifestName)) {
    $FileAcl = [IO.File]::GetAccessControl($Path)
    $FileAcl.SetOwner(
        [Security.Principal.SecurityIdentifier]"S-1-5-32-544"
    )
    [IO.File]::SetAccessControl($Path, $FileAcl)
}

Write-Host "Protected runtime staged. No credential was copied."
