# src/api/app/main.py
"""
Point d'entrée FastAPI pour le service "Agent QA & Test Automation".
Contient l'initialisation de l'application, configuration CORS, routes principales
et gestion du cycle de vie (startup/shutdown) pour les clients (vectorstore, model, sandbox).
"""

from fastapi import FastAPI, Request, Depends
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
import logging
import asyncio

from app.api.endpoints import router as api_router
from app.core.orchestrator import Orchestrator
from app.core.config import settings  # suppose un module config avec les settings

logger = logging.getLogger("agent_qa")
logging.basicConfig(level=logging.INFO)


def create_app() -> FastAPI:
    app = FastAPI(
        title="Agent QA & Test Automation",
        description="Orchestrateur pour génération/exécution/analyse de tests via agents IA",
        version="0.1.0",
    )

    # CORS (adapter selon ton déploiement)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.CORS_ALLOW_ORIGINS or ["http://localhost:7860"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # Routes
    app.include_router(api_router, prefix="/api")

    # Health
    @app.get("/health", tags=["health"])
    async def health():
        return {"status": "ok"}

    # Exception handler simple (peut être enrichi)
    @app.exception_handler(Exception)
    async def generic_exception_handler(request: Request, exc: Exception):
        logger.exception("Unhandled exception: %s", exc)
        return JSONResponse(
            status_code=500,
            content={"detail": "Internal server error"},
        )

    # Lifecycle: orchestrator instance attachée à l'app.state
    @app.on_event("startup")
    async def on_startup():
        logger.info("Starting application and initializing orchestrator clients...")
        # Créer les clients (vectorstore, model, sandbox) dans orchestrator
        orchestrator = Orchestrator.from_settings(settings)
        # Si Orchestrator a des initialisations async, les appeler ici
        if hasattr(orchestrator, "async_init"):
            await orchestrator.async_init()
        app.state.orchestrator = orchestrator
        logger.info("Orchestrator initialized.")

    @app.on_event("shutdown")
    async def on_shutdown():
        logger.info("Shutting down application and cleaning up orchestrator...")
        orchestrator: Orchestrator | None = getattr(app.state, "orchestrator", None)
        if orchestrator:
            # appeler cleanup sync/async si disponible
            if hasattr(orchestrator, "async_close"):
                await orchestrator.async_close()
            elif hasattr(orchestrator, "close"):
                orchestrator.close()
        logger.info("Cleanup complete.")

    return app


# Dependency pour récupérer l'orchestrator dans les endpoints
def get_orchestrator(request: Request) -> Orchestrator:
    orchestrator = getattr(request.app.state, "orchestrator", None)
    if orchestrator is None:
        raise RuntimeError("Orchestrator not initialized")
    return orchestrator


# Application exposée pour uvicorn / ASGI
app = create_app()

# Exemple d'endpoint local utilisant la dépendance (peut être déplacé dans app.api.endpoints)
@app.get("/api/ping", tags=["debug"])
async def ping(orchestrator: Orchestrator = Depends(get_orchestrator)):
    """
    Endpoint de debug rapide pour vérifier la disponibilité de l'orchestrator.
    """
    try:
        # si orchestrator expose une méthode health_check, l'appeler
        if hasattr(orchestrator, "health_check"):
            ok = await asyncio.get_event_loop().run_in_executor(None, orchestrator.health_check)
            return {"orchestrator": "ok" if ok else "unhealthy"}
    except Exception:
        logger.exception("Error during orchestrator health check")
    return {"orchestrator": "initialized"}
