[CmdletBinding(SupportsShouldProcess = $true, ConfirmImpact = "High")]
param(
    [ValidateNotNullOrEmpty()]
    [string]$UserId = "$env:USERDOMAIN\$env:USERNAME",

    [ValidateRange(60, 90)]
    [int]$StartupDelaySeconds = 75,

    [bool]$IncludeLogonFallback = $true
)

$ErrorActionPreference = "Stop"

$taskName = "SportsModel - Dashboard"
$repositoryRoot = Split-Path -Parent $PSScriptRoot
$launcherPath = Join-Path $PSScriptRoot "run_dashboard.ps1"
$powerShellPath = Join-Path `
    $env:SystemRoot `
    "System32\WindowsPowerShell\v1.0\powershell.exe"

if (-not (Test-Path -LiteralPath $launcherPath)) {
    throw "Dashboard launcher was not found: $launcherPath"
}

$actionArguments = (
    '-NoProfile -WindowStyle Hidden -ExecutionPolicy Bypass ' +
    '-File "{0}" -Port 8501' -f $launcherPath
)

$action = New-ScheduledTaskAction `
    -Execute $powerShellPath `
    -Argument $actionArguments `
    -WorkingDirectory $repositoryRoot

$startupTrigger = New-ScheduledTaskTrigger -AtStartup
$startupTrigger.Delay = "PT${StartupDelaySeconds}S"
$triggers = @($startupTrigger)

if ($IncludeLogonFallback) {
    $triggers += New-ScheduledTaskTrigger `
        -AtLogOn `
        -User $UserId
}

$principal = New-ScheduledTaskPrincipal `
    -UserId $UserId `
    -LogonType S4U `
    -RunLevel Limited

$settings = New-ScheduledTaskSettingsSet `
    -MultipleInstances IgnoreNew `
    -RestartCount 3 `
    -RestartInterval (New-TimeSpan -Minutes 1) `
    -ExecutionTimeLimit ([TimeSpan]::Zero) `
    -StartWhenAvailable `
    -AllowStartIfOnBatteries `
    -DontStopIfGoingOnBatteries

$task = New-ScheduledTask `
    -Action $action `
    -Trigger $triggers `
    -Principal $principal `
    -Settings $settings `
    -Description (
        "SportsModel read-only Streamlit dashboard. Starts after boot without " +
        "interactive logon and retains logon as a recovery fallback."
    )

if ($PSCmdlet.ShouldProcess(
    "\$taskName",
    "Register exact repository-managed Dashboard task definition"
)) {
    Register-ScheduledTask `
        -TaskName $taskName `
        -InputObject $task `
        -Force | Out-Null

    Write-Host "Registered scheduled task: \$taskName"
}
