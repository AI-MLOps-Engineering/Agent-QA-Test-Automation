# tmp_orchestrator.py
# Remplace le fichier orchestrator.py dans le conteneur API par cette version.
# (Contenu complet, mis Ã  jour pour rÃ©cupÃ©rer analysis depuis disque si absent en mÃ©moire.)

from __future__ import annotations

import asyncio
import json
import logging
import os
import shutil
import tempfile
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Optional, Tuple

from app.core.config import settings

logger = logging.getLogger("agent_qa.orchestrator")


class VectorStoreClient:
    def __init__(self, url: Optional[str] = None, api_key: Optional[str] = None):
        self.url = url
        self.api_key = api_key

    async def upsert_documents(self, namespace: str, docs: list[dict]):
        logger.debug("VectorStore.upsert_documents namespace=%s docs=%d", namespace, len(docs))

    async def query(self, namespace: str, query: str, top_k: int = 5) -> list[dict]:
        logger.debug("VectorStore.query namespace=%s query=%s", namespace, query)
        return []


class ModelClient:
    def __init__(self, url: Optional[str] = None, default_model: str = "code-model"):
        self.url = url
        self.default_model = default_model

    async def generate(self, prompt: str, max_tokens: int = 1024) -> str:
        logger.debug("ModelClient.generate prompt_len=%d", len(prompt))
        return f"[model-output] (simulated) summary of prompt: {prompt[:200]}"

    async def close(self):
        pass


class SandboxClient:
    def __init__(self, image: str = settings.SANDBOX_IMAGE):
        self.image = image

    async def run_tests(self, repo_path: str, tests_path: str, timeout_seconds: int = 120) -> dict:
        logger.debug("SandboxClient.run_tests repo=%s tests=%s timeout=%s", repo_path, tests_path, timeout_seconds)
        await asyncio.sleep(0.1)
        return {
            "status": "completed",
            "passed": 0,
            "failed": 0,
            "duration_seconds": 0.1,
            "artifacts": {"junit": None, "coverage": None, "logs": None},
            "raw": {},
        }

    async def close(self):
        pass


def write_json_atomic(path: str, obj: Any) -> None:
    dirpath = os.path.dirname(path)
    os.makedirs(dirpath, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=dirpath)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            json.dump(obj, fh, ensure_ascii=False, indent=2)
            fh.flush()
            os.fsync(fh.fileno())
        os.replace(tmp, path)
    finally:
        if os.path.exists(tmp):
            try:
                os.remove(tmp)
            except Exception:
                logger.debug("Failed to remove tmp file %s", tmp)


@dataclass
class RepoRecord:
    repo_id: str
    path: str


class Orchestrator:
    def __init__(self, vector_client: VectorStoreClient, model_client: ModelClient, sandbox_client: SandboxClient):
        self.vector = vector_client
        self.model = model_client
        self.sandbox = sandbox_client

        self._repos: dict[str, RepoRecord] = {}
        self._analyses: dict[str, dict] = {}
        self._tests: dict[str, dict] = {}
        self._runs: dict[str, dict] = {}

        self.artifacts_root = Path(settings.ARTIFACTS_ROOT)
        self.artifacts_root.mkdir(parents=True, exist_ok=True)

    @classmethod
    def from_settings(cls, cfg: settings.__class__ | None = None) -> "Orchestrator":
        cfg = cfg or settings
        vector = VectorStoreClient(url=str(cfg.VECTORSTORE_URL) if cfg.VECTORSTORE_URL else None, api_key=cfg.VECTORSTORE_API_KEY)
        model = ModelClient(url=str(cfg.MODEL_SERVER_URL) if cfg.MODEL_SERVER_URL else None, default_model=cfg.MODEL_DEFAULT_NAME)
        sandbox = SandboxClient(image=cfg.SANDBOX_IMAGE)
        return cls(vector_client=vector, model_client=model, sandbox_client=sandbox)

    async def async_init(self):
        logger.info("Orchestrator.async_init: initializing clients (if needed)")

    async def async_close(self):
        logger.info("Orchestrator.async_close: closing clients")
        try:
            await self.model.close()
        except Exception:
            logger.exception("Error closing model client")
        try:
            await self.sandbox.close()
        except Exception:
            logger.exception("Error closing sandbox client")

    def close(self):
        logger.info("Orchestrator.close called")

    async def register_repo(self, repo_id: str, path: str) -> None:
        logger.info("Registering repo %s -> %s", repo_id, path)
        self._repos[repo_id] = RepoRecord(repo_id=repo_id, path=path)

    async def analyze_repo(self, repo_path: str, entrypoint: Optional[str] = None) -> Tuple[str, str]:
        logger.info("Analyzing repo at %s (entrypoint=%s)", repo_path, entrypoint)
        analysis_id = str(uuid.uuid4())
        summary = await self._run_reader_agent(repo_path, entrypoint)
        self._analyses[analysis_id] = {"repo_path": repo_path, "entrypoint": entrypoint, "summary": summary}
        analysis_dir = self.artifacts_root / "analyses" / analysis_id
        analysis_dir.mkdir(parents=True, exist_ok=True)
        write_json_atomic(str(analysis_dir / "summary.json"), {"analysis_id": analysis_id, "summary": summary, "repo_path": repo_path})
        logger.info("Analysis complete: %s", analysis_id)
        return analysis_id, summary

    async def _run_reader_agent(self, repo_path: str, entrypoint: Optional[str]) -> str:
        loop = asyncio.get_event_loop()
        summary = await loop.run_in_executor(None, self._sync_extract_and_index, repo_path, entrypoint)
        return summary

    def _sync_extract_and_index(self, repo_path: str, entrypoint: Optional[str]) -> str:
        docs = []
        repo_path = Path(repo_path)
        for py_file in repo_path.rglob("*.py"):
            try:
                text = py_file.read_text(encoding="utf-8", errors="ignore")
                snippet = "\n".join(text.splitlines()[:20])
                docs.append({"path": str(py_file.relative_to(repo_path)), "content": snippet})
            except Exception:
                logger.exception("Failed to read %s", py_file)
        try:
            asyncio.run(self.vector.upsert_documents(namespace=str(repo_path), docs=docs))
        except Exception:
            logger.exception("Vector upsert failed (placeholder)")
        summary = f"Repository at {repo_path.name}: {len(docs)} python files indexed."
        return summary

    async def generate_tests(self, analysis_id: str, target: str = "all", coverage_goal: float = 0.8) -> Tuple[str, int]:
        logger.info("Generating tests for analysis=%s target=%s coverage_goal=%s", analysis_id, target, coverage_goal)
        analysis = self._analyses.get(analysis_id)

        # If analysis not in memory, attempt to recover from disk
        if not analysis:
            analysis_dir = self.artifacts_root / "analyses" / analysis_id
            summary_file = analysis_dir / "summary.json"
            if summary_file.exists():
                try:
                    data = json.loads(summary_file.read_text(encoding="utf-8"))
                    summary_text = data.get("summary")
                    repo_path = data.get("repo_path") or str(self.artifacts_root)
                    analysis = {"repo_path": repo_path, "entrypoint": None, "summary": summary_text}
                    self._analyses[analysis_id] = analysis
                    logger.info("Recovered analysis %s from disk (repo_path=%s)", analysis_id, repo_path)
                except Exception:
                    logger.exception("Failed to load analysis summary.json for %s", analysis_id)
            else:
                raise FileNotFoundError("analysis_id not found")

        repo_path = analysis["repo_path"]

        tests_id = str(uuid.uuid4())
        tests_dir = self.artifacts_root / "tests" / tests_id
        tests_dir.mkdir(parents=True, exist_ok=True)

        prompt = f"Generate {target} tests for repository summary: {analysis.get('summary')}\nCoverage goal: {coverage_goal}"
        rag_docs = await self.vector.query(namespace=str(repo_path), query="generate tests", top_k=5)
        model_output = await self.model.generate(prompt=prompt, max_tokens=2048)

        test_file = tests_dir / "test_generated_sample.py"
        test_content = (
            '"""\n'
            "Auto-generated tests (simulated)\n"
            "Model output summary:\n"
            f"{model_output}\n"
            '"""\n\n'
            "import pytest\n\n\n"
            "def test_placeholder():\n"
            "    assert True\n"
        )
        test_file.write_text(test_content, encoding="utf-8")

        files_generated = 1

        tests_meta = {"analysis_id": analysis_id, "tests_dir": str(tests_dir), "files_generated": files_generated, "repo_path": repo_path}
        self._tests[tests_id] = tests_meta
        try:
            write_json_atomic(str(tests_dir / "meta.json"), tests_meta)
        except Exception:
            logger.exception("Failed to write meta.json for tests_id=%s", tests_id)

        logger.info("Tests generated: tests_id=%s files=%d", tests_id, files_generated)
        return tests_id, files_generated

    async def run_tests(self, tests_id: str, run_id: Optional[str] = None, timeout_seconds: Optional[int] = None) -> dict:
        logger.info("Running tests tests_id=%s run_id=%s", tests_id, run_id)
        tests_meta = self._tests.get(tests_id)

        if not tests_meta:
            meta_path = self.artifacts_root / "tests" / tests_id / "meta.json"
            tests_dir_on_disk = self.artifacts_root / "tests" / tests_id
            if meta_path.exists():
                try:
                    tests_meta = json.loads(meta_path.read_text(encoding="utf-8"))
                    logger.info("Loaded tests_meta from meta.json for tests_id=%s", tests_id)
                    self._tests[tests_id] = tests_meta
                except Exception:
                    logger.exception("Failed to parse meta.json for tests_id=%s", tests_id)
            elif tests_dir_on_disk.exists() and tests_dir_on_disk.is_dir():
                tests_meta = {"analysis_id": None, "tests_dir": str(tests_dir_on_disk), "files_generated": len(list(tests_dir_on_disk.glob('*')))}
                logger.info("Recovered tests_meta from disk for tests_id=%s tests_dir=%s", tests_id, tests_dir_on_disk)
                self._tests[tests_id] = tests_meta
            else:
                raise FileNotFoundError("tests_id not found")

        run_id = run_id or str(uuid.uuid4())
        timeout_seconds = int(timeout_seconds or settings.SANDBOX_TIMEOUT)

        repo_path = None
        if tests_meta.get("analysis_id"):
            analysis = self._analyses.get(tests_meta["analysis_id"])
            if analysis:
                repo_path = analysis.get("repo_path")
        if not repo_path:
            repo_path = tests_meta.get("repo_path") or str(self.artifacts_root)

        run_dir = self.artifacts_root / "runs" / run_id
        if run_dir.exists():
            shutil.rmtree(run_dir)
        run_dir.mkdir(parents=True, exist_ok=True)

        try:
            results = await self.sandbox.run_tests(repo_path=repo_path, tests_path=tests_meta["tests_dir"], timeout_seconds=timeout_seconds)
        except Exception as e:
            logger.exception("Sandbox execution failed: %s", e)
            results = {"status": "error", "error": str(e)}

        artifacts = results.get("artifacts") or {}
        if not artifacts:
            try:
                for p in run_dir.iterdir():
                    if p.is_file() and p.name != "results.json":
                        artifacts[p.name] = str(p)
                artifacts_dir = run_dir / "artifacts"
                if artifacts_dir.exists() and artifacts_dir.is_dir():
                    for p in artifacts_dir.rglob("*"):
                        if p.is_file():
                            artifacts[p.name] = str(p)
            except Exception:
                logger.exception("Failed to collect artifacts from run_dir=%s", run_dir)

        raw = results.get("raw", {})
        results_record = {
            "run_id": run_id,
            "tests_id": tests_id,
            "status": results.get("status", "unknown"),
            "summary": {
                "passed": results.get("passed"),
                "failed": results.get("failed"),
                "duration_seconds": results.get("duration_seconds"),
            },
            "artifacts": artifacts,
            "raw": raw,
        }

        try:
            write_json_atomic(str(run_dir / "results.json"), results_record)
        except Exception:
            logger.exception("Failed to write results.json for run_id=%s", run_id)

        self._runs[run_id] = {"meta": results_record, "dir": str(run_dir)}
        logger.info("Run persisted: run_id=%s status=%s", run_id, results_record.get("status"))
        return results_record

    async def store_run_failure(self, run_id: str, error: str) -> None:
        logger.info("Storing run failure for %s", run_id)
        run_dir = self.artifacts_root / "runs" / run_id
        run_dir.mkdir(parents=True, exist_ok=True)
        failure_record = {"run_id": run_id, "status": "failed", "error": error}
        try:
            write_json_atomic(str(run_dir / "results.json"), failure_record)
        except Exception:
            logger.exception("Failed to write failure results.json for run_id=%s", run_id)
        self._runs[run_id] = {"meta": failure_record, "dir": str(run_dir)}

    async def get_run_report(self, run_id: str) -> dict:
        run = self._runs.get(run_id)
        if not run:
            run_dir = self.artifacts_root / "runs" / run_id
            results_file = run_dir / "results.json"
            if not results_file.exists():
                raise FileNotFoundError("run_id not found")
            data = json.loads(results_file.read_text(encoding="utf-8"))
            artifacts = {}
            for p in run_dir.iterdir():
                if p.is_file():
                    artifacts[p.name] = str(p)
            return {"run_id": data.get("run_id", run_id), "status": data.get("status", "unknown"), "summary": data.get("summary", ""), "artifacts": artifacts}
        else:
            meta = run["meta"]
            run_dir = Path(run["dir"])
            artifacts = {}
            for p in run_dir.iterdir():
                if p.is_file():
                    artifacts[p.name] = str(p)
            return {"run_id": meta.get("run_id", run_id), "status": meta.get("status", "unknown"), "summary": meta.get("summary", ""), "artifacts": artifacts}

    async def get_run_artifact_path(self, run_id: str, artifact_name: str) -> str:
        run = self._runs.get(run_id)
        run_dir = Path(run["dir"]) if run else (self.artifacts_root / "runs" / run_id)
        artifact_path = run_dir / artifact_name
        if not artifact_path.exists():
            raise FileNotFoundError("artifact not found")
        return str(artifact_path)

    async def analyze_results(self, run_id: str) -> dict:
        logger.info("Analyzing results for run_id=%s", run_id)
        report = await self.get_run_report(run_id)
        prompt = f"Analyze test run results: {json.dumps(report.get('summary', {}))}\nPropose fixes and a patch diff if applicable."
        model_output = await self.model.generate(prompt=prompt, max_tokens=1024)
        suggestions = {"analysis": model_output, "patch_diff": None}
        run_dir = self.artifacts_root / "runs" / run_id
        try:
            write_json_atomic(str(run_dir / "analysis.json"), suggestions)
        except Exception:
            logger.exception("Failed to write analysis.json for run_id=%s", run_id)
        return suggestions

    async def check_vectorstore(self) -> bool:
        try:
            await self.vector.query(namespace="health", query="ping", top_k=1)
            return True
        except Exception:
            logger.exception("Vectorstore health check failed")
            return False

    async def check_model_server(self) -> bool:
        try:
            await self.model.generate(prompt="health check", max_tokens=4)
            return True
        except Exception:
            logger.exception("Model server health check failed")
            return False

    async def check_sandbox(self) -> bool:
        try:
            await self.sandbox.run_tests(repo_path=str(self.artifacts_root), tests_path=str(self.artifacts_root), timeout_seconds=1)
            return True
        except Exception:
            logger.exception("Sandbox health check failed")
            return False

    async def health_check(self) -> bool:
        checks = await asyncio.gather(
            self.check_vectorstore(),
            self.check_model_server(),
            self.check_sandbox(),
            return_exceptions=False,
        )
        return all(bool(c) for c in checks)
