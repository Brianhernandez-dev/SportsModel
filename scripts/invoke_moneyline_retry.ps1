Set-StrictMode -Version Latest


$script:MoneylineRetryableExitCode = 75
$script:MoneylineFailureClassificationKey = (
    "SportsModelFailureClassification"
)


function New-MoneylineRetryableException {
    [CmdletBinding()]
    param(
        [Parameter(Mandatory)]
        [string]$Message
    )

    $Exception = [InvalidOperationException]::new($Message)
    $Exception.Data[$script:MoneylineFailureClassificationKey] = "transient"
    return $Exception
}


function Test-MoneylineRetryableException {
    [CmdletBinding()]
    param(
        [Parameter(Mandatory)]
        [Exception]$Exception
    )

    return (
        $Exception.Data[$script:MoneylineFailureClassificationKey] -eq
        "transient"
    )
}


function Invoke-MoneylineOperationWithRetry {
    [CmdletBinding()]
    param(
        [Parameter(Mandatory)]
        [string]$OperationName,

        [Parameter(Mandatory)]
        [scriptblock]$Preflight,

        [Parameter(Mandatory)]
        [scriptblock]$Operation,

        [int]$MaxAttempts = 4,

        [int]$RetryDelaySeconds = 900,

        [scriptblock]$Logger,

        [scriptblock]$NowProvider = { [DateTimeOffset]::Now },

        [scriptblock]$Sleeper = {
            param([int]$Seconds)
            Start-Sleep -Seconds $Seconds
        }
    )

    if ($MaxAttempts -le 0) {
        throw "MaxAttempts must be greater than zero."
    }

    if ($RetryDelaySeconds -lt 0) {
        throw "RetryDelaySeconds cannot be negative."
    }

    function Write-RetryLog {
        param([Parameter(Mandatory)][string]$Message)

        if ($null -ne $Logger) {
            & $Logger $Message
            return
        }

        Write-Host $Message
    }

    for ($Attempt = 1; $Attempt -le $MaxAttempts; $Attempt++) {
        Write-RetryLog (
            "$OperationName attempt $Attempt/${MaxAttempts}: " +
            "running scheduled/PIT and database preflight."
        )

        $PreflightResult = $null
        $FailureMessage = $null
        $FailureIsRetryable = $false

        try {
            $PreflightResult = & $Preflight
        }
        catch {
            $FailureMessage = $_.Exception.Message
            $FailureIsRetryable = Test-MoneylineRetryableException `
                -Exception $_.Exception
        }

        if ($null -eq $FailureMessage) {
            try {
                $ExitCode = & $Operation
            }
            catch {
                $FailureMessage = $_.Exception.Message
                $FailureIsRetryable = Test-MoneylineRetryableException `
                    -Exception $_.Exception
            }

            if ($null -eq $FailureMessage) {
                if ($ExitCode -eq 0) {
                    Write-RetryLog (
                        "$OperationName attempt $Attempt/$MaxAttempts " +
                        "completed successfully."
                    )
                    return
                }

                $FailureMessage = (
                    "$OperationName exited with code $ExitCode."
                )
                $FailureIsRetryable = (
                    $ExitCode -eq $script:MoneylineRetryableExitCode
                )
            }
        }

        if ($FailureIsRetryable) {
            $Classification = "transient"
        }
        else {
            $Classification = "permanent/nonretryable"
        }
        Write-RetryLog (
            "$OperationName attempt $Attempt/$MaxAttempts failed. " +
            "Classification: $Classification. $FailureMessage"
        )

        if (-not $FailureIsRetryable) {
            throw (
                "$OperationName will not be retried after a " +
                "permanent/nonretryable failure. $FailureMessage"
            )
        }

        if ($Attempt -eq $MaxAttempts) {
            throw (
                "$OperationName exhausted $MaxAttempts attempts after " +
                "proven transient failures. Final failure: " +
                "$FailureMessage"
            )
        }

        $Now = & $NowProvider
        $NextRetryTime = $Now.AddSeconds($RetryDelaySeconds)
        $LatestValidStartTime = $null

        if (
            $null -ne $PreflightResult -and
            $null -ne $PreflightResult.PSObject.Properties[
                "LatestValidStartTime"
            ]
        ) {
            $LatestValidStartTime = (
                $PreflightResult.LatestValidStartTime
            )
        }

        if ($null -ne $LatestValidStartTime) {
            $RemainingWindow = $LatestValidStartTime - $Now
            Write-RetryLog (
                "Remaining PIT window: " +
                "$([math]::Max(0, [int]$RemainingWindow.TotalSeconds)) " +
                "seconds; latest valid start " +
                "$($LatestValidStartTime.ToString('o'))."
            )

            if ($NextRetryTime -ge $LatestValidStartTime) {
                throw (
                    "$OperationName retry refused because the next " +
                    "attempt at $($NextRetryTime.ToString('o')) would " +
                    "reach or cross the PIT deadline " +
                    "$($LatestValidStartTime.ToString('o'))."
                )
            }
        }
        else {
            Write-RetryLog (
                "Remaining PIT window: unavailable from the failed " +
                "preflight; validity will be re-evaluated before retry."
            )
        }

        Write-RetryLog (
            "$OperationName next retry: " +
            "$($NextRetryTime.ToString('o')); delay " +
            "$RetryDelaySeconds seconds."
        )
        & $Sleeper $RetryDelaySeconds
    }
}
