# poll-report.ps1
# Remplace la valeur ciâ€‘dessous par le run_id renvoyÃ© par le serveur si nÃ©cessaire
$serverRunId = "0ce7fb2d-ae64-416d-a1c7-2aa0d3b40001"
$timeoutSeconds = 600
$start = Get-Date

while ( (Get-Date) - $start ).TotalSeconds -lt $timeoutSeconds {
  try {
    $report = Invoke-RestMethod -Uri "http://localhost:8000/api/report/$serverRunId" -Method Get -ErrorAction Stop
    Write-Host "Report disponible"
    $report | ConvertTo-Json -Depth 10 | Out-File -FilePath ".\report-$serverRunId.json" -Encoding utf8
    Write-Host "Rapport sauvegardÃ© dans report-$serverRunId.json"
    exit 0
  } catch {
    Write-Host "Rapport non prÃªt, attente 5s..."
    Start-Sleep -Seconds 5
  }
}

Write-Host "Timeout atteint sans rapport. VÃ©rifie les logs du serveur."
exit 1
