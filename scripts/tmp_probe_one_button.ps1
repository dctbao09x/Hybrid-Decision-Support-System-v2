Set-Location "f:\Hybrid Decision Support System"

$endpoints = @(
  "http://127.0.0.1:8000/api/v1/one-button/run",
  "http://127.0.0.1:8000/api/v1/decision/run"
)

foreach ($ep in $endpoints) {
  $respFile = "$env:TEMP\hdss_probe_resp.json"
  if (Test-Path $respFile) {
    Remove-Item $respFile -Force -ErrorAction SilentlyContinue
  }

  $metrics = curl.exe -sS --max-time 120 -o $respFile -w "HTTP_STATUS:%{http_code};TOTAL:%{time_total}" -H "Content-Type: application/json" --data-binary "@scripts/one_button_payload.json" $ep
  $httpStatus = ""
  if ($metrics -match "HTTP_STATUS:(\d+)") {
    $httpStatus = $Matches[1]
  }

  Write-Output "ENDPOINT=$ep"
  Write-Output $metrics
  if ($httpStatus) {
    Write-Output "STATUS_CODE=$httpStatus"
  }

  if (Test-Path $respFile) {
    $raw = Get-Content -Raw $respFile
    if ($raw.Length -gt 0) {
      try {
        $j = $raw | ConvertFrom-Json
        if ($j.status) {
          Write-Output "PIPELINE_STATUS=$($j.status)"
        }
        if ($j.market_data) {
          Write-Output "MARKET_STATUS=$($j.market_data.status)"
          Write-Output "MARKET_TAXONOMY=$($j.market_data.taxonomy)"
        }
        if ($j.reasoning) {
          Write-Output "REASONING=$($j.reasoning)"
        }
        if ($j.error) {
          Write-Output "ERROR=$($j.error)"
        }
        if ($j.message) {
          Write-Output "MESSAGE=$($j.message)"
        }
        if ($j.detail) {
          Write-Output "DETAIL=$($j.detail)"
        }
        if (-not $j.status -and -not $j.error -and -not $j.detail) {
          Write-Output "RAW_JSON=$raw"
        }
      }
      catch {
        Write-Output "RAW_BODY=$raw"
      }
    }
    else {
      Write-Output "RAW_BODY=<empty>"
    }
  }

  Write-Output "---"
}
