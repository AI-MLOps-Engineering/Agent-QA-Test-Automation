# tests/integration/test_api_endpoints.py
"""
Integration tests for API endpoints (upload, analyze, generate, run, report).

These tests use FastAPI's TestClient against the application factory defined in
src/api/app/main.py. To avoid external dependencies (vectorstore, model server,
docker), we inject a MockOrchestrator into app.state during tests.

Run with:
    pytest tests/integration/test_api_endpoints.py -q
"""

import io
import json
import os
import shutil
import tempfile
import zipfile
import uuid
from pathlib import Path
from typing import Dict, Any, Optional

import pytest
from fastapi.testclient import TestClient

# Import the app factory and settings
from app.main import create_app  # adjust import path if running tests from repo root
from app.core.config import settings  # to get UPLOAD_ROOT override if needed


# NOTE: depending on your PYTHONPATH/test runner, you may need to adjust imports:
# from src.api.app.main import create_app
# from src.api.app.core.config import settings


class MockOrchestrator:
    """
    Minimal mock orchestrator implementing the async methods used by endpoints.
    Stores simple in-memory records for repos, analyses, tests and runs.
    """

    def __init__(self):
        self._repos: Dict[str, str] = {}
        self._analyses: Dict[str, Dict[str, Any]] = {}
        self._tests: Dict[str, Dict[str, Any]] = {}
        self._runs: Dict[str, Dict[str, Any]] = {}

    @classmethod
    def from_settings(cls, *args, **kwargs):
        # Keep compatibility with Orchestrator.from_settings usage in app startup
        return cls()

    async def async_init(self):
        return None

    async def async_close(self):
        return None

    async def register_repo(self, repo_id: str, path: str) -> None:
        self._repos[repo_id] = path

    async def analyze_repo(self, repo_path: str, entrypoint: Optional[str] = None):
        # create analysis id and summary
        analysis_id = str(uuid.uuid4())
        summary = f"Mock analysis for {Path(repo_path).name}"
        self._analyses[analysis_id] = {"repo_path": repo_path, "entrypoint": entrypoint, "summary": summary}
        return analysis_id, summary

    async def generate_tests(self, analysis_id: str, target: str = "all", coverage_goal: float = 0.8):
        if analysis_id not in self._analyses:
            raise FileNotFoundError("analysis_id not found")
        tests_id = str(uuid.uuid4())
        tests_dir = tempfile.mkdtemp(prefix="mock_tests_")
        # create a simple test file
        test_file = Path(tests_dir) / "test_generated_sample.py"
        test_file.write_text("def test_always_passes():\n    assert True\n", encoding="utf-8")
        self._tests[tests_id] = {"analysis_id": analysis_id, "tests_dir": tests_dir, "files_generated": 1}
        return tests_id, 1

    async def run_tests(self, tests_id: str, run_id: Optional[str] = None, timeout_seconds: Optional[int] = None):
        if tests_id not in self._tests:
            raise FileNotFoundError("tests_id not found")
        run_id = run_id or str(uuid.uuid4())
        tests_meta = self._tests[tests_id]
        repo_path = self._analyses[tests_meta["analysis_id"]]["repo_path"]
        # Simulate a completed run and write a results.json artifact
        run_dir = Path(tempfile.mkdtemp(prefix="mock_run_")) / run_id
        run_dir.mkdir(parents=True, exist_ok=True)
        results = {
            "run_id": run_id,
            "tests_id": tests_id,
            "status": "completed",
            "summary": {"passed": 1, "failed": 0, "duration_seconds": 0.1},
            "artifacts": {"junit.xml": str(run_dir / "junit.xml")},
            "raw": {},
        }
        (run_dir / "results.json").write_text(json.dumps(results), encoding="utf-8")
        # create a dummy junit file
        (run_dir / "junit.xml").write_text("<testsuite tests='1' failures='0'/>", encoding="utf-8")
        self._runs[run_id] = {"meta": results, "dir": str(run_dir)}
        return results

    async def store_run_failure(self, run_id: str, error: str) -> None:
        run_dir = Path(tempfile.mkdtemp(prefix="mock_run_")) / run_id
        run_dir.mkdir(parents=True, exist_ok=True)
        failure_record = {"run_id": run_id, "status": "failed", "error": error}
        (run_dir / "results.json").write_text(json.dumps(failure_record), encoding="utf-8")
        self._runs[run_id] = {"meta": failure_record, "dir": str(run_dir)}

    async def get_run_report(self, run_id: str) -> Dict[str, Any]:
        run = self._runs.get(run_id)
        if not run:
            # try to load from disk
            run_dir = Path(settings.ARTIFACTS_ROOT) / "runs" / run_id
            results_file = run_dir / "results.json"
            if not results_file.exists():
                raise FileNotFoundError("run_id not found")
            data = json.loads(results_file.read_text(encoding="utf-8"))
            artifacts = {p.name: str(p) for p in run_dir.iterdir() if p.is_file()}
            return {"status": data.get("status", "unknown"), "summary": data.get("summary", ""), "artifacts": artifacts}
        meta = run["meta"]
        run_dir = Path(run["dir"])
        artifacts = {p.name: str(p) for p in run_dir.iterdir() if p.is_file()}
        return {"status": meta.get("status", "unknown"), "summary": meta.get("summary", ""), "artifacts": artifacts}

    async def get_run_artifact_path(self, run_id: str, artifact_name: str) -> str:
        run = self._runs.get(run_id)
        if not run:
            raise FileNotFoundError("run_id not found")
        run_dir = Path(run["dir"])
        artifact_path = run_dir / artifact_name
        if not artifact_path.exists():
            raise FileNotFoundError("artifact not found")
        return str(artifact_path)

    async def health_check(self) -> bool:
        return True


@pytest.fixture
def client(tmp_path, monkeypatch):
    """
    Create a TestClient with a MockOrchestrator injected into app.state.
    Also override UPLOAD_ROOT to a temporary directory to avoid polluting /tmp.
    """
    # Ensure settings use a temp upload root and artifacts root
    upload_root = tmp_path / "uploads"
    artifacts_root = tmp_path / "artifacts"
    upload_root.mkdir()
    artifacts_root.mkdir()
    monkeypatch.setenv("UPLOAD_ROOT", str(upload_root))
    monkeypatch.setenv("ARTIFACTS_ROOT", str(artifacts_root))

    # Create app and inject mock orchestrator during startup
    app = create_app()

    # Replace orchestrator factory to return our mock
    mock_orch = MockOrchestrator()
    # Attach mock orchestrator to app.state before TestClient startup handlers run
    app.state.orchestrator = mock_orch

    with TestClient(app) as tc:
        yield tc


def _make_repo_zip(tmp_dir: Path, files: Dict[str, str]) -> bytes:
    """
    Create an in-memory zip archive representing a small repo.
    `files` is a mapping of relative path -> file content.
    Returns bytes of the zip file.
    """
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        for rel_path, content in files.items():
            zf.writestr(rel_path, content)
    buf.seek(0)
    return buf.read()


def test_upload_and_analyze_flow(client: TestClient, tmp_path: Path):
    # 1) Create a small repo zip
    files = {
        "src/__init__.py": "",
        "src/app.py": "def hello():\n    return 'world'\n",
        "README.md": "# sample repo",
    }
    zip_bytes = _make_repo_zip(tmp_path, files)

    # Upload repo
    resp = client.post("/api/upload-repo", files={"file": ("repo.zip", io.BytesIO(zip_bytes), "application/zip")})
    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert "repo_id" in data and data["repo_id"], data
    repo_id = data["repo_id"]

    # Analyze repo
    resp = client.post("/api/analyze", json={"repo_id": repo_id})
    assert resp.status_code == 200, resp.text
    analysis = resp.json()
    assert "analysis_id" in analysis and analysis["analysis_id"]
    assert "summary" in analysis and isinstance(analysis["summary"], str)


def test_generate_and_run_tests_flow(client: TestClient, tmp_path: Path):
    # Prepare and upload repo
    files = {"module.py": "def add(a,b):\n    return a+b\n"}
    zip_bytes = _make_repo_zip(tmp_path, files)
    resp = client.post("/api/upload-repo", files={"file": ("repo.zip", io.BytesIO(zip_bytes), "application/zip")})
    assert resp.status_code == 200
    repo_id = resp.json()["repo_id"]

    # Analyze
    resp = client.post("/api/analyze", json={"repo_id": repo_id})
    assert resp.status_code == 200
    analysis_id = resp.json()["analysis_id"]

    # Generate tests
    resp = client.post("/api/generate-tests", json={"analysis_id": analysis_id, "target": "unit", "coverage_goal": 0.8})
    assert resp.status_code == 200, resp.text
    gen = resp.json()
    assert "tests_id" in gen and gen["tests_id"]
    tests_id = gen["tests_id"]

    # Run tests (this schedules a background task; TestClient runs background tasks synchronously)
    resp = client.post("/api/run-tests", json={"tests_id": tests_id})
    assert resp.status_code == 200
    run_info = resp.json()
    assert "run_id" in run_info and run_info["run_id"]
    run_id = run_info["run_id"]

    # Retrieve report (should be available because MockOrchestrator.run_tests completes immediately)
    resp = client.get(f"/api/report/{run_id}")
    assert resp.status_code == 200, resp.text
    report = resp.json()
    assert report["run_id"] == run_id
    assert "status" in report
    assert "artifacts" in report and isinstance(report["artifacts"], dict)

    # If an artifact exists, try to download it via the artifact endpoint
    artifacts = report.get("artifacts", {})
    if artifacts:
        # pick first artifact name
        artifact_name = next(iter(artifacts.keys()))
        dl_resp = client.get(f"/api/report/{run_id}/artifact/{artifact_name}")
        # The MockOrchestrator returns a real file path, so the endpoint should stream it
        assert dl_resp.status_code == 200, dl_resp.text


def test_report_not_found(client: TestClient):
    # Requesting a non-existent run should return 404
    resp = client.get("/api/report/non-existent-run-id")
    assert resp.status_code == 404
