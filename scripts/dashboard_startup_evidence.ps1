Set-StrictMode -Version Latest


function New-SportsModelDashboardStartupEvidence {
    [CmdletBinding()]
    param(
        [Parameter(Mandatory)]
        [string]$LogDirectory,

        [DateTimeOffset]$UtcNow = [DateTimeOffset]::UtcNow,

        [int]$ProcessId = $PID,

        [string]$AttemptNonce = [Guid]::NewGuid().ToString("N")
    )

    if ([string]::IsNullOrWhiteSpace($LogDirectory)) {
        throw "Dashboard startup log directory must not be empty."
    }

    if ([string]::IsNullOrWhiteSpace($AttemptNonce)) {
        throw "Dashboard startup attempt nonce must not be empty."
    }

    $null = New-Item `
        -ItemType Directory `
        -Path $LogDirectory `
        -Force

    $Timestamp = $UtcNow.ToUniversalTime().ToString(
        "yyyyMMdd'T'HHmmss.fffffff'Z'"
    )
    $AttemptId = "$Timestamp-pid$ProcessId-$AttemptNonce"
    $LogPath = Join-Path `
        $LogDirectory `
        "dashboard_startup_$AttemptId.log"

    return [pscustomobject]@{
        AttemptId = $AttemptId
        LogPath = $LogPath
    }
}


function Write-SportsModelDashboardStartupEvidence {
    [CmdletBinding()]
    param(
        [Parameter(Mandatory)]
        [pscustomobject]$Evidence,

        [Parameter(Mandatory)]
        [AllowEmptyString()]
        [string]$Message,

        [DateTimeOffset]$UtcNow = [DateTimeOffset]::UtcNow
    )

    $Timestamp = $UtcNow.ToUniversalTime().ToString("o")
    $Line = "[$Timestamp] attempt=$($Evidence.AttemptId) $Message"

    Add-Content `
        -LiteralPath $Evidence.LogPath `
        -Value $Line `
        -Encoding UTF8

    Write-Host $Line
}
