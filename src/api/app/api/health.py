# src/api/app/api/health.py
"""
Health, liveness and readiness endpoints for the Agent QA & Test Automation service.

Endpoints:
- GET /api/health         : overall health summary (lightweight)
- GET /api/health/live    : liveness probe (is app running)
- GET /api/health/ready   : readiness probe (are dependencies available)
- GET /api/metrics        : basic metrics placeholder (optional)
"""

from __future__ import annotations

import logging
import time
from typing import Dict, Any

from fastapi import APIRouter, Request, Depends
from fastapi.responses import JSONResponse

from app.api.main import get_orchestrator
from app.core.orchestrator import Orchestrator

logger = logging.getLogger("agent_qa.health")

router = APIRouter()


def _component_status(ok: bool, details: str | None = None) -> Dict[str, Any]:
    return {"ok": bool(ok), "details": details or ""}


@router.get("/health", tags=["health"])
async def health_summary(request: Request, orchestrator: Orchestrator = Depends(get_orchestrator)):
    """
    Lightweight health summary combining liveness and quick readiness checks.
    Returns a JSON object with component statuses and a short summary.
    """
    start = time.time()
    status = {"service": "agent-qa-test-automation", "timestamp": int(start)}

    # Liveness: if the app is responding, it's live
    status["liveness"] = _component_status(True, "application responding")

    # Readiness: check orchestrator clients if available
    try:
        # orchestrator may expose sync or async health methods for each client
        vector_ok = model_ok = sandbox_ok = None

        if hasattr(orchestrator, "check_vectorstore"):
            vector_ok = await _maybe_call(orchestrator.check_vectorstore)
        if hasattr(orchestrator, "check_model_server"):
            model_ok = await _maybe_call(orchestrator.check_model_server)
        if hasattr(orchestrator, "check_sandbox"):
            sandbox_ok = await _maybe_call(orchestrator.check_sandbox)

        # Build readiness map
        readiness = {}
        readiness["vectorstore"] = _component_status(vector_ok is not False, None if vector_ok else "unavailable")
        readiness["model_server"] = _component_status(model_ok is not False, None if model_ok else "unavailable")
        readiness["sandbox"] = _component_status(sandbox_ok is not False, None if sandbox_ok else "unavailable")

        # Overall readiness: all known components must be ok
        overall_ready = all(v["ok"] for v in readiness.values())
        status["readiness"] = {"ok": overall_ready, "components": readiness}
    except Exception as e:
        logger.exception("Error while computing readiness: %s", e)
        status["readiness"] = {"ok": False, "error": str(e)}

    status["response_ms"] = int((time.time() - start) * 1000)
    return JSONResponse(status_code=200 if status["readiness"].get("ok", False) else 503, content=status)


@router.get("/health/live", tags=["health"])
async def liveness_probe():
    """
    Liveness probe for orchestration systems (Kubernetes, systemd, etc).
    Should be extremely lightweight.
    """
    return JSONResponse(status_code=200, content={"live": True})


@router.get("/health/ready", tags=["health"])
async def readiness_probe(orchestrator: Orchestrator = Depends(get_orchestrator)):
    """
    Readiness probe: verifies that required external services are reachable.
    Returns 200 when ready, 503 otherwise.
    """
    checks = {}
    try:
        if hasattr(orchestrator, "check_vectorstore"):
            checks["vectorstore"] = await _maybe_call(orchestrator.check_vectorstore)
        else:
            checks["vectorstore"] = None

        if hasattr(orchestrator, "check_model_server"):
            checks["model_server"] = await _maybe_call(orchestrator.check_model_server)
        else:
            checks["model_server"] = None

        if hasattr(orchestrator, "check_sandbox"):
            checks["sandbox"] = await _maybe_call(orchestrator.check_sandbox)
        else:
            checks["sandbox"] = None

        # Interpret None as "not configured" (not failing readiness)
        failing = [k for k, v in checks.items() if v is False]
        ready = len(failing) == 0
        content = {"ready": ready, "checks": checks}
        return JSONResponse(status_code=200 if ready else 503, content=content)
    except Exception as e:
        logger.exception("Readiness probe error: %s", e)
        return JSONResponse(status_code=503, content={"ready": False, "error": str(e)})


@router.get("/metrics", tags=["health"])
async def metrics_placeholder():
    """
    Basic metrics endpoint placeholder.
    Replace with Prometheus client exposition if needed.
    """
    # Minimal example metrics; in production use prometheus_client.generate_latest()
    metrics = {
        "uptime_seconds": 0,  # to be implemented: track app start time
        "active_runs": 0,     # to be implemented: query orchestrator or store
    }
    return JSONResponse(status_code=200, content=metrics)


# Utility helper to call sync or async methods uniformly
async def _maybe_call(fn, *args, **kwargs):
    """
    Call a function that may be sync or async. Return its result.
    If the function raises, return False.
    """
    try:
        result = fn(*args, **kwargs)
        # If result is awaitable, await it
        if hasattr(result, "__await__"):
            result = await result
        return result
    except Exception:
        logger.exception("Dependency health check failed for %s", getattr(fn, "__name__", str(fn)))
        return False
