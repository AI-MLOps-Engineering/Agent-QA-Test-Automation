# e2e-integration.ps1
param(
  [string]$ApiBase = "http://localhost:8000",
  [string]$analysisId = "350f1934-3b29-4567-a8db-5e1daacb732a",
  [int]$runTimeoutSeconds = 600,
  [int]$pollIntervalSeconds = 2
)

function ExitWith($code, $msg) {
  Write-Host $msg
  exit $code
}

if (-not $analysisId) {
  Write-Host "Aucun analysisId fourni. Tu peux fournir -analysisId <id> ou créer une analyse via l'API."
  ExitWith 2 "Abandon."
}

# 1. Generate tests
$payload = @{ analysis_id = $analysisId; target = "all"; coverage_goal = 0.8 } | ConvertTo-Json
Write-Host "Calling generate-tests for analysis_id=$analysisId ..."
try {
  $genResp = Invoke-RestMethod -Uri "$ApiBase/api/generate-tests" -Method Post -ContentType 'application/json' -Body $payload -ErrorAction Stop
} catch {
  ExitWith 3 "generate-tests failed: $($_.Exception.Response.Content.ReadAsStringAsync().Result)"
}
Write-Host "generate-tests response:"
$genResp | Format-List

$testsId = $genResp.tests_id
if (-not $testsId) { ExitWith 4 "No tests_id returned." }

# 2. Verify meta.json exists in container filesystem
Write-Host "Checking meta.json for tests_id=$testsId ..."
docker compose exec api sh -c "test -f /data/artifacts/tests/$testsId/meta.json && echo 'META_OK' || echo 'META_MISSING'" | Out-Host

# 3. Launch run
$payloadRun = @{ tests_id = $testsId; timeout_seconds = $runTimeoutSeconds } | ConvertTo-Json
Write-Host "Calling run-tests for tests_id=$testsId ..."
try {
  $runResp = Invoke-RestMethod -Uri "$ApiBase/api/run-tests" -Method Post -ContentType 'application/json' -Body $payloadRun -ErrorAction Stop
} catch {
  ExitWith 5 "run-tests failed: $($_.Exception.Response.Content.ReadAsStringAsync().Result)"
}
Write-Host "run-tests response:"
$runResp | Format-List

$runId = $runResp.run_id
if (-not $runId) { ExitWith 6 "No run_id returned." }

# 4. Poll for results.json presence and valid JSON
$elapsed = 0
$resultsPath = "/data/artifacts/runs/$runId/results.json"
Write-Host "Polling for results.json at $resultsPath ..."
while ($elapsed -lt $runTimeoutSeconds) {
  $exists = docker compose exec api sh -c "test -f $resultsPath && echo '1' || echo '0'" 2>$null
  if ($exists -match "1") { break }
  Start-Sleep -Seconds $pollIntervalSeconds
  $elapsed += $pollIntervalSeconds
}
if ($elapsed -ge $runTimeoutSeconds) { ExitWith 7 "Timed out waiting for results.json" }

# 5. Fetch and validate results.json
Write-Host "Fetching results.json ..."
docker compose exec api sh -c "cat $resultsPath" | Out-Host

Write-Host "Validating JSON..."
$validate = docker compose exec api sh -c "python - <<'PY'
import json,sys
p='$resultsPath'
try:
    json.load(open(p,'r',encoding='utf-8'))
    print('RESULTS_JSON_OK')
except Exception as e:
    print('RESULTS_JSON_INVALID', e)
    sys.exit(1)
PY"
if ($validate -notmatch "RESULTS_JSON_OK") { ExitWith 8 "results.json invalid" }

# 6. Print summary and artifacts
Write-Host "Run completed and results.json valid. Summary:"
docker compose exec api sh -c "python - <<'PY'
import json
p='/data/artifacts/runs/$runId/results.json'
d=json.load(open(p,'r',encoding='utf-8'))
print('run_id:', d.get('run_id'))
print('status:', d.get('status'))
print('summary:', d.get('summary'))
print('artifacts:', d.get('artifacts'))
PY"

Write-Host "Integration test finished successfully."
exit 0
