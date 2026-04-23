param(
  [string]$Endpoint = "http://127.0.0.1:8000/api/v1/one-button/run",
  [int]$TimeoutSec = 120
)

Set-Location "f:\Hybrid Decision Support System"
$body = Get-Content -Raw "scripts\one_button_payload.json"

$sw = [System.Diagnostics.Stopwatch]::StartNew()
try {
  $resp = Invoke-WebRequest -Method Post -Uri $Endpoint -ContentType "application/json" -Body $body -TimeoutSec $TimeoutSec -UseBasicParsing
  $sw.Stop()
  Write-Output "ENDPOINT=$Endpoint"
  Write-Output "STATUS=$($resp.StatusCode)"
  Write-Output "ELAPSED_MS=$($sw.ElapsedMilliseconds)"
  if ($resp.Content) {
    Write-Output "BODY=$($resp.Content)"
  }
}
catch {
  $sw.Stop()
  $statusCode = ""
  if ($_.Exception.Response -and $_.Exception.Response.StatusCode) {
    $statusCode = $_.Exception.Response.StatusCode.value__
  }
  Write-Output "ENDPOINT=$Endpoint"
  Write-Output "STATUS=$statusCode"
  Write-Output "ELAPSED_MS=$($sw.ElapsedMilliseconds)"
  Write-Output "ERROR=$($_.Exception.Message)"
  if ($_.ErrorDetails -and $_.ErrorDetails.Message) {
    Write-Output "ERROR_BODY=$($_.ErrorDetails.Message)"
  }
}
