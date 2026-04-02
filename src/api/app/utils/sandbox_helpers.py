# src/api/app/utils/sandbox_helpers.py
"""
Helpers to run tests in an isolated sandbox environment.

This module provides a small, well-documented API used by the Orchestrator to:
- prepare a sandbox workspace for a repository and generated tests
- run tests inside an isolated Docker container (or a subprocess fallback)
- collect artifacts (junit xml, coverage, logs)
- parse basic results and return a normalized dict

Design goals:
- Keep side effects explicit (work in a provided workspace directory)
- Prefer Docker for isolation; fall back to a subprocess runner if Docker is unavailable
- Enforce resource limits and timeouts
- Return structured results suitable for persistence by the Orchestrator
- Avoid executing untrusted code on the host outside the sandbox workspace
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import shlex
import shutil
import subprocess
import tempfile
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from app.core.config import settings

logger = logging.getLogger("agent_qa.sandbox_helpers")


@dataclass
class SandboxResult:
    status: str  # "completed" | "timeout" | "error"
    passed: Optional[int]
    failed: Optional[int]
    duration_seconds: float
    artifacts: Dict[str, Optional[str]]  # artifact name -> path (on host)
    raw: Dict[str, object]


# -------------------------
# Utilities
# -------------------------
def _ensure_dir(path: Path) -> None:
    path.mkdir(parents=True, exist_ok=True)


def _copy_repo_to_workspace(repo_path: str, workspace: Path) -> Path:
    """
    Copy repository files into the workspace. We copy only the repository contents,
    not the parent directories, to avoid leaking host paths into the container.
    Returns the path to the repo inside the workspace.
    """
    src = Path(repo_path)
    if not src.exists():
        raise FileNotFoundError(f"repo_path not found: {repo_path}")

    dest = workspace / "repo"
    if dest.exists():
        shutil.rmtree(dest)
    shutil.copytree(src, dest, symlinks=False, ignore_dangling_symlinks=True)
    return dest


def _copy_tests_to_workspace(tests_path: str, workspace: Path) -> Path:
    """
    Copy generated tests into the workspace under tests/.
    """
    src = Path(tests_path)
    if not src.exists():
        raise FileNotFoundError(f"tests_path not found: {tests_path}")

    dest = workspace / "tests"
    if dest.exists():
        shutil.rmtree(dest)
    shutil.copytree(src, dest, symlinks=False, ignore_dangling_symlinks=True)
    return dest


def _build_docker_run_command(
    workspace: Path,
    image: str,
    timeout_seconds: int,
    cpu_limit: Optional[str] = None,
    mem_limit: Optional[str] = None,
    allow_network: bool = False,
) -> List[str]:
    """
    Build a docker run command that mounts the workspace and runs the sandbox entrypoint.
    The container is expected to run tests and write artifacts to /sandbox/artifacts inside the container.
    """
    mounts = [
        f"-v{workspace.as_posix()}:/workspace:ro"  # repo and tests mounted read-only by default
    ]
    # Provide a writable artifacts directory
    artifacts_host = workspace / "artifacts"
    _ensure_dir(artifacts_host)
    mounts.append(f"-v{artifacts_host.as_posix()}:/sandbox/artifacts:rw")

    # Security flags
    flags = [
        "--rm",
        "--network=none" if not allow_network else "--network=bridge",
        "--pids-limit=512",
        "--read-only",
    ]
    if cpu_limit:
        flags.append(f"--cpus={cpu_limit}")
    if mem_limit:
        flags.append(f"--memory={mem_limit}")

    # Drop capabilities
    flags.append("--cap-drop=ALL")
    # Prevent privilege escalation
    flags.append("--security-opt=no-new-privileges")

    # Compose full command
    cmd = ["docker", "run"] + flags
    for m in mounts:
        cmd.append(m)
    # Environment variables (pass minimal)
    cmd += ["-e", f"SANDBOX_TIMEOUT={timeout_seconds}"]
    # Image and entrypoint: the image should contain an entrypoint that runs tests and writes artifacts
    cmd.append(image)
    return cmd


async def _run_subprocess(cmd: List[str], timeout: int) -> Tuple[int, str, str]:
    """
    Run a subprocess asynchronously and capture stdout/stderr.
    Returns (returncode, stdout, stderr).
    """
    logger.debug("Running subprocess: %s", " ".join(shlex.quote(c) for c in cmd))
    proc = await asyncio.create_subprocess_exec(
        *cmd, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE
    )
    try:
        stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=timeout)
        return proc.returncode, stdout.decode(errors="ignore"), stderr.decode(errors="ignore")
    except asyncio.TimeoutError:
        proc.kill()
        await proc.wait()
        return -1, "", "timeout"


# -------------------------
# Public API
# -------------------------
async def run_tests_in_sandbox(
    repo_path: str,
    tests_path: str,
    timeout_seconds: Optional[int] = None,
    image: Optional[str] = None,
    cpu_limit: Optional[str] = None,
    mem_limit: Optional[str] = None,
    allow_network: Optional[bool] = None,
) -> Dict[str, object]:
    """
    High-level helper to run tests in an isolated sandbox.

    Steps:
    - Create a temporary workspace
    - Copy repo and tests into the workspace
    - Run tests inside Docker (preferred) or fallback to a subprocess runner
    - Collect artifacts (junit xml, coverage, logs)
    - Parse basic results and return a normalized dict

    Returns a dict compatible with Orchestrator.run_tests placeholder results.
    """
    start_time = time.time()
    timeout_seconds = int(timeout_seconds or settings.SANDBOX_TIMEOUT)
    image = image or settings.SANDBOX_IMAGE
    cpu_limit = cpu_limit or settings.SANDBOX_CPU_LIMIT
    mem_limit = mem_limit or settings.SANDBOX_MEM_LIMIT
    allow_network = bool(allow_network if allow_network is not None else settings.ALLOW_SANDBOX_NETWORK)

    workspace = Path(tempfile.mkdtemp(prefix="agent_qa_sandbox_"))
    logger.info("Created sandbox workspace: %s", workspace)

    try:
        # Copy repo and tests
        repo_dest = _copy_repo_to_workspace(repo_path, workspace)
        tests_dest = _copy_tests_to_workspace(tests_path, workspace)

        # Prepare artifacts dir
        artifacts_dir = workspace / "artifacts"
        _ensure_dir(artifacts_dir)

        # Build docker command
        docker_cmd = _build_docker_run_command(
            workspace=workspace,
            image=image,
            timeout_seconds=timeout_seconds,
            cpu_limit=cpu_limit,
            mem_limit=mem_limit,
            allow_network=allow_network,
        )

        # The container image is expected to run tests automatically when started.
        # If Docker is available, use it; otherwise fallback to running pytest locally inside the workspace.
        use_docker = shutil.which("docker") is not None
        logger.debug("Docker available: %s", use_docker)

        if use_docker:
            # Run docker with timeout enforced by asyncio
            # Note: docker run will block until container exits; we rely on the container entrypoint to respect SANDBOX_TIMEOUT.
            cmd = docker_cmd
            # If the image expects an entrypoint/command, the image should handle it.
            rc, out, err = await _run_subprocess(cmd, timeout=timeout_seconds + 5)
            stdout = out
            stderr = err
            if rc == -1:
                status = "timeout"
            elif rc == 0:
                status = "completed"
            else:
                status = "error"
        else:
            # Fallback: run pytest directly in a subprocess inside the workspace (less secure)
            logger.warning("Docker not available; running tests in local subprocess (less secure).")
            # Build pytest command: run tests in tests/ and output junit xml and coverage
            junit_path = artifacts_dir / "junit.xml"
            coverage_dir = artifacts_dir / "coverage"
            _ensure_dir(coverage_dir)
            cmd = [
                "pytest",
                str(tests_dest),
                "--maxfail=1",
                "--disable-warnings",
                "-q",
                f"--junitxml={junit_path}",
                "--cov",
                str(repo_dest),
                f"--cov-report=xml:{coverage_dir / 'coverage.xml'}",
            ]
            rc, out, err = await _run_subprocess(cmd, timeout=timeout_seconds)
            stdout = out
            stderr = err
            if rc == -1:
                status = "timeout"
            elif rc == 0:
                status = "completed"
            else:
                status = "error"

        duration = time.time() - start_time

        # Collect artifacts: look for junit.xml, coverage.xml, logs
        artifacts = {}
        # Search artifacts_dir for common files
        for candidate in ["junit.xml", "results.xml", "coverage.xml", "coverage.xml", "pytest.log"]:
            p = artifacts_dir / candidate
            if p.exists():
                artifacts[candidate] = str(p)
        # Always capture stdout/stderr into files for inspection
        stdout_file = artifacts_dir / "sandbox_stdout.log"
        stderr_file = artifacts_dir / "sandbox_stderr.log"
        stdout_file.write_text(stdout or "", encoding="utf-8")
        stderr_file.write_text(stderr or "", encoding="utf-8")
        artifacts["sandbox_stdout.log"] = str(stdout_file)
        artifacts["sandbox_stderr.log"] = str(stderr_file)

        # Try to parse junit to get passed/failed counts
        passed, failed = _parse_junit_counts(artifacts_dir)

        result = SandboxResult(
            status=status,
            passed=passed,
            failed=failed,
            duration_seconds=duration,
            artifacts={k: v for k, v in artifacts.items()},
            raw={"stdout": stdout[:2000] if stdout else "", "stderr": stderr[:2000] if stderr else ""},
        )

        return {
            "status": result.status,
            "passed": result.passed,
            "failed": result.failed,
            "duration_seconds": result.duration_seconds,
            "artifacts": result.artifacts,
            "raw": result.raw,
        }
    except Exception as e:
        logger.exception("Sandbox execution error: %s", e)
        duration = time.time() - start_time
        return {
            "status": "error",
            "passed": None,
            "failed": None,
            "duration_seconds": duration,
            "artifacts": {},
            "raw": {"error": str(e)},
        }
    finally:
        # Note: we intentionally do NOT delete the workspace here so that artifacts can be inspected by callers.
        # The caller/orchestrator is responsible for cleanup if desired.
        logger.info("Sandbox workspace available at: %s", workspace)


# -------------------------
# Helpers for parsing artifacts
# -------------------------
def _parse_junit_counts(artifacts_dir: Path) -> Tuple[Optional[int], Optional[int]]:
    """
    Look for junit XML files in artifacts_dir and return (passed, failed).
    If no junit found, return (None, None).
    """
    try:
        import xml.etree.ElementTree as ET
    except Exception:
        logger.exception("Failed to import xml parser")
        return None, None

    junit_files = list(artifacts_dir.glob("**/junit*.xml")) + list(artifacts_dir.glob("**/results*.xml"))
    if not junit_files:
        return None, None

    total_passed = 0
    total_failed = 0
    for jf in junit_files:
        try:
            tree = ET.parse(jf)
            root = tree.getroot()
            # JUnit XML may have attributes 'tests', 'failures', 'errors', 'skipped'
            tests = int(root.attrib.get("tests", 0))
            failures = int(root.attrib.get("failures", 0)) + int(root.attrib.get("errors", 0))
            skipped = int(root.attrib.get("skipped", 0))
            passed = tests - failures - skipped
            total_passed += max(0, passed)
            total_failed += max(0, failures)
        except Exception:
            logger.exception("Failed to parse junit file %s", jf)
            continue

    return total_passed, total_failed
