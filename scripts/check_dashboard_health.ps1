[CmdletBinding()]
param(
    [ValidateRange(1, 65535)]
    [int]$Port = 8501,

    [ValidateRange(1, 30)]
    [int]$TimeoutSeconds = 5
)

$ErrorActionPreference = "Stop"

. (Join-Path $PSScriptRoot "dashboard_health.ps1")

$health = Get-SportsModelDashboardHealth `
    -Port $Port `
    -TimeoutSeconds $TimeoutSeconds

Write-Host "Listener: $($health.ListenerPresent)"
Write-Host "HTTP:     $($health.HttpStatusCode)"
Write-Host "URL:      $($health.HealthUrl)"

if ($health.Healthy) {
    Write-Host "Dashboard healthy"
    exit 0
}

if ($health.ErrorMessage) {
    Write-Error $health.ErrorMessage
}
else {
    Write-Error "Dashboard health check failed."
}

exit 1
