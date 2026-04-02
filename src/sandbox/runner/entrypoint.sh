#!/usr/bin/env bash
# src/sandbox/runner/entrypoint.sh
#
# Entrypoint pour l'image sandbox. Conçu pour être exécuté dans un conteneur isolé.
# - attend que le repo soit monté sous /workspace (read-only)
# - écrit les artefacts dans /sandbox/artifacts (rw)
# - exécute pytest avec junit + coverage
# - respecte SANDBOX_TIMEOUT (seconds)
# - capture stdout/stderr dans des fichiers pour inspection
#
# Usage: l'image doit définir ce script comme ENTRYPOINT ou CMD.
set -euo pipefail

# Configuration (peut être surchargée via env)
SANDBOX_TIMEOUT=${SANDBOX_TIMEOUT:-120}
WORKDIR=${WORKDIR:-/workspace}
ARTIFACTS_DIR=${ARTIFACTS_DIR:-/sandbox/artifacts}
TESTS_DIR=${TESTS_DIR:-/workspace/tests}
REPO_DIR=${REPO_DIR:-/workspace/repo}
JUNIT_FILE="${ARTIFACTS_DIR}/junit.xml"
COVERAGE_XML="${ARTIFACTS_DIR}/coverage.xml"
STDOUT_LOG="${ARTIFACTS_DIR}/sandbox_stdout.log"
STDERR_LOG="${ARTIFACTS_DIR}/sandbox_stderr.log"
PYTEST_ARGS=${PYTEST_ARGS:-"--maxfail=1 --disable-warnings -q"}

# Ensure artifacts dir exists and is writable
mkdir -p "${ARTIFACTS_DIR}"
chmod 700 "${ARTIFACTS_DIR}"

# Helper to write timestamped messages
_log() {
  echo "[$(date --iso-8601=seconds)] $*" >> "${ARTIFACTS_DIR}/entrypoint.log"
}

# Trap signals to allow graceful shutdown
_graceful_exit() {
  _log "Received termination signal, exiting."
  # attempt to copy partial logs if any (already in ARTIFACTS_DIR)
  exit 143
}
trap _graceful_exit SIGTERM SIGINT

_log "Sandbox entrypoint starting"
_log "WORKDIR=${WORKDIR} TESTS_DIR=${TESTS_DIR} REPO_DIR=${REPO_DIR} SANDBOX_TIMEOUT=${SANDBOX_TIMEOUT}"

# Validate workspace
if [ ! -d "${WORKDIR}" ]; then
  _log "ERROR: workspace ${WORKDIR} not found"
  echo "Workspace not found: ${WORKDIR}" > "${STDERR_LOG}"
  exit 2
fi

# Determine test target: prefer tests/ then repo root
if [ -d "${TESTS_DIR}" ] && [ "$(ls -A "${TESTS_DIR}")" ]; then
  TARGET="${TESTS_DIR}"
elif [ -d "${REPO_DIR}" ] && [ -f "${REPO_DIR}/pytest.ini" ] || [ -d "${REPO_DIR}" ]; then
  TARGET="${REPO_DIR}"
else
  _log "No tests or repo found to run"
  echo "No tests found" > "${STDERR_LOG}"
  exit 0
fi

_log "Running tests in target: ${TARGET}"

# Build pytest command
PYTEST_CMD=(pytest ${PYTEST_ARGS} --junitxml="${JUNIT_FILE}" --cov="${REPO_DIR}" --cov-report=xml:"${COVERAGE_XML}" "${TARGET}")

# Use timeout if available to enforce SANDBOX_TIMEOUT
if command -v timeout >/dev/null 2>&1; then
  _log "Using timeout command to enforce ${SANDBOX_TIMEOUT}s"
  CMD=(timeout --preserve-status "${SANDBOX_TIMEOUT}" "${PYTEST_CMD[@]}")
else
  # fallback: run pytest and rely on internal timeouts
  _log "timeout command not available; running pytest without external timeout"
  CMD=("${PYTEST_CMD[@]}")
fi

# Run tests, capture stdout/stderr
_log "Executing: ${CMD[*]}"
# shellcheck disable=SC2086
if "${CMD[@]}" > >(tee "${STDOUT_LOG}") 2> >(tee "${STDERR_LOG}" >&2); then
  RC=0
  _log "Tests completed successfully"
else
  RC=$?
  _log "Tests finished with return code ${RC}"
fi

# Ensure junit and coverage files exist (create placeholders if missing)
if [ ! -f "${JUNIT_FILE}" ]; then
  _log "junit file missing; creating placeholder"
  cat > "${JUNIT_FILE}" <<EOF
<testsuite tests="0" failures="0" />
EOF
fi

if [ ! -f "${COVERAGE_XML}" ]; then
  _log "coverage xml missing; creating placeholder"
  cat > "${COVERAGE_XML}" <<EOF
<?xml version="1.0"?>
<coverage/>
EOF
fi

# Summarize results (basic)
_passed_count=0
_failed_count=0
if command -v xmllint >/dev/null 2>&1 && [ -f "${JUNIT_FILE}" ]; then
  # try to extract attributes safely
  _tests=$(xmllint --xpath "string(/testsuite/@tests)" "${JUNIT_FILE}" 2>/dev/null || echo "")
  _failures=$(xmllint --xpath "string(/testsuite/@failures)" "${JUNIT_FILE}" 2>/dev/null || echo "")
  if [ -n "${_tests}" ]; then _passed_count=$(( ${_tests:-0} - ${_failures:-0} )); fi
  _failed_count=${_failures:-0}
fi

_log "Result summary: rc=${RC} passed=${_passed_count} failed=${_failed_count}"
# Write a small results.json for orchestrator to consume
cat > "${ARTIFACTS_DIR}/results.json" <<EOF
{
  "status": "$( [ "${RC}" -eq 0 ] && echo "completed" || echo "failed" )",
  "passed": ${_passed_count},
  "failed": ${_failed_count},
  "duration_seconds": 0,
  "artifacts": {
    "junit": "$(basename "${JUNIT_FILE}")",
    "coverage": "$(basename "${COVERAGE_XML}")",
    "stdout": "$(basename "${STDOUT_LOG}")",
    "stderr": "$(basename "${STDERR_LOG}")"
  }
}
EOF

# Exit with pytest return code (0 success, non-zero failure)
exit "${RC}"
