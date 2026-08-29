Set-StrictMode -Version Latest

function Get-SportsModelDashboardHealth {
    [CmdletBinding()]
    param(
        [ValidateRange(1, 65535)]
        [int]$Port = 8501,

        [ValidateRange(1, 30)]
        [int]$TimeoutSeconds = 5
    )

    $listenerPresent = $false
    $httpStatusCode = $null
    $errorMessage = $null

    $tcpClient = [System.Net.Sockets.TcpClient]::new()

    try {
        $connectTask = $tcpClient.ConnectAsync("127.0.0.1", $Port)
        if (-not $connectTask.Wait([TimeSpan]::FromSeconds($TimeoutSeconds))) {
            throw "TCP connection timed out."
        }

        if ($connectTask.IsFaulted) {
            throw $connectTask.Exception.GetBaseException()
        }

        $listenerPresent = $tcpClient.Connected
    }
    catch {
        $errorMessage = $_.Exception.Message
    }
    finally {
        $tcpClient.Dispose()
    }

    if ($listenerPresent) {
        try {
            $response = Invoke-WebRequest `
                -UseBasicParsing `
                -Uri "http://127.0.0.1:$Port/_stcore/health" `
                -TimeoutSec $TimeoutSeconds `
                -ErrorAction Stop

            $httpStatusCode = [int]$response.StatusCode
        }
        catch {
            $errorMessage = $_.Exception.Message
        }
    }

    [pscustomobject]@{
        Healthy = (
            $listenerPresent `
            -and $httpStatusCode -eq 200
        )
        ListenerPresent = $listenerPresent
        HttpStatusCode = $httpStatusCode
        ErrorMessage = $errorMessage
        HealthUrl = "http://127.0.0.1:$Port/_stcore/health"
    }
}
