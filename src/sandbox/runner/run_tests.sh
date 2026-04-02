#!/usr/bin/env bash
# src/sandbox/runner/run_tests.sh
#
# Lightweight runner used by the sandbox image to execute tests for a mounted repo.
# Usage: run_tests.sh <repo_dir>
# Writes JUnit XML to /sandbox/results/results.xml and a small results.json summary.
set -euo pipefail

REPO_DIR=${1:-}
RESULTS_DIR=${RESULTS_DIR:-/sandbox/results}
JUNIT_FILE="${RESULTS_DIR}/results.xml"
STDOUT_LOG="${RESULTS_DIR}/stdout.log"
STDERR_LOG="${RESULTS_DIR}/stderr.log"
SANDBOX_TIMEOUT=${SANDBOX_TIMEOUT:-120}

if [ -z "${REPO_DIR}" ]; then
  echo "Usage: $0 <repo_dir>" >&2
  exit 2
fi

mkdir -p "${RESULTS_DIR}"
chmod 700 "${RESULTS_DIR}"

_log() {
  echo "[$(date --iso-8601=seconds)] $*" >> "${RESULTS_DIR}/runner.log"
}

_log "Starting test runner for repo: ${REPO_DIR}"
_log "SANDBOX_TIMEOUT=${SANDBOX_TIMEOUT}"

# Ensure pytest is available
if ! command -v pytest >/dev/null 2>&1; then
  echo "pytest not found in PATH" > "${STDERR_LOG}"
  _log "ERROR: pytest not found"
  cat > "${RESULTS_DIR}/results.json" <<EOF
{"status":"error","error":"pytest not available","passed":null,"failed":null,"duration_seconds":0}
EOF
  exit 3
fi

# Build pytest command
JUNIT_ARG="--junitxml=${JUNIT_FILE}"
COV_ARG="--cov=${REPO_DIR} --cov-report=xml:${RESULTS_DIR}/coverage.xml"
PYTEST_ARGS=(pytest -q --maxfail=1 --disable-warnings "${JUNIT_ARG}" "${COV_ARG}" "${REPO_DIR}")

# Run with timeout if available
_start_time=$(date +%s)
if command -v timeout >/dev/null 2>&1; then
  _log "Using timeout to enforce ${SANDBOX_TIMEOUT}s"
  if timeout --preserve-status "${SANDBOX_TIMEOUT}" "${PYTEST_ARGS[@]}" > >(tee "${STDOUT_LOG}") 2> >(tee "${STDERR_LOG}" >&2); then
    RC=0
  else
    RC=$?
    # timeout returns 124 on timeout; normalize to -1 for clarity
    if [ "${RC}" -eq 124 ]; then
      RC=-1
    fi
  fi
else
  _log "timeout command not available; running pytest without external timeout"
  if "${PYTEST_ARGS[@]}" > >(tee "${STDOUT_LOG}") 2> >(tee "${STDERR_LOG}" >&2); then
    RC=0
  else
    RC=$?
  fi
fi
_end_time=$(date +%s)
_duration=$((_end_time - _start_time))

# Normalize status
if [ "${RC}" -eq 0 ]; then
  STATUS="completed"
elif [ "${RC}" -eq -1 ]; then
  STATUS="timeout"
else
  STATUS="failed"
fi

# Ensure junit exists (create minimal placeholder if missing)
if [ ! -f "${JUNIT_FILE}" ]; then
  _log "JUnit file missing; creating placeholder"
  cat > "${JUNIT_FILE}" <<EOF
<testsuite tests="0" failures="0"/>
EOF
fi

# Try to parse junit to extract passed/failed counts (best-effort)
PASSED=null
FAILED=null
if command -v python3 >/dev/null 2>&1; then
  PASSED=$(python3 - <<PY
import xml.etree.ElementTree as ET, sys
try:
    tree = ET.parse("${JUNIT_FILE}")
    root = tree.getroot()
    tests = int(root.attrib.get("tests", "0"))
    failures = int(root.attrib.get("failures", "0")) + int(root.attrib.get("errors", "0"))
    skipped = int(root.attrib.get("skipped", "0"))
    passed = tests - failures - skipped
    print(passed)
except Exception:
    print("null")
PY
)
  FAILED=$(python3 - <<PY
import xml.etree.ElementTree as ET, sys
try:
    tree = ET.parse("${JUNIT_FILE}")
    root = tree.getroot()
    failures = int(root.attrib.get("failures", "0")) + int(root.attrib.get("errors", "0"))
    print(failures)
except Exception:
    print("null")
PY
)
fi

# Write results.json
cat > "${RESULTS_DIR}/results.json" <<EOF
{
  "status": "${STATUS}",
  "passed": ${PASSED},
  "failed": ${FAILED},
  "duration_seconds": ${_duration},
  "artifacts": {
    "junit": "$(basename "${JUNIT_FILE}")",
    "coverage": "coverage.xml",
    "stdout": "$(basename "${STDOUT_LOG}")",
    "stderr": "$(basename "${STDERR_LOG}")"
  }
}
EOF

_log "Test run finished: status=${STATUS} passed=${PASSED} failed=${FAILED} duration=${_duration}s rc=${RC}"
exit $(( RC == -1 ? 124 : (RC) ))
