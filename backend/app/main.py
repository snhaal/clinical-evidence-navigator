"""
FastAPI entrypoint.

Wires up the application, CORS middleware, database connection lifespan,
health check endpoints, and the clinical trial matching & verification router
(Plan -> Act -> Ground -> Verify -> Synthesize pipeline).
"""

import logging
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.routes import router as match_router
from app.config import get_settings
from app.db import dispose_engine, healthcheck

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    settings = get_settings()
    logger.info(
        "Starting Clinical Evidence Navigator API (env=%s)", settings.environment
    )
    yield
    await dispose_engine()
    logger.info("Shut down cleanly.")


def create_app() -> FastAPI:
    settings = get_settings()

    app = FastAPI(
        title="Clinical Evidence Navigator API",
        description=(
            "Agentic RAG system matching patient profiles to clinical trials "
            "with cited, criterion-level reasoning. Not a medical device."
        ),
        version="0.1.0",
        lifespan=lifespan,
    )

    # Normalize app_url and allow preview/local origins
    app_origin = str(settings.app_url).rstrip("/")
    allowed_origins = [app_origin, "http://localhost:3000", "http://127.0.0.1:3000"]

    app.add_middleware(
        CORSMiddleware,
        allow_origins=allowed_origins,
        allow_origin_regex=r"https://clinical-evidence-navigator.*\.vercel\.app",
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    @app.get("/health")
    async def health() -> dict:
        db_ok = await healthcheck()
        return {
            "status": "ok" if db_ok else "degraded",
            "database": "connected" if db_ok else "unreachable",
        }

    @app.get("/")
    async def root() -> dict:
        return {
            "service": "clinical-evidence-navigator",
            "disclaimer": (
                "Portfolio engineering project. Not a medical device. "
                "Not a substitute for clinical judgment."
            ),
        }

    # Clinical Trial Matching, Verification & History Endpoints
    app.include_router(match_router)
    app.include_router(match_router, prefix="/api")
    app.include_router(match_router, prefix="/api/v1")

    return app


app = create_app()
