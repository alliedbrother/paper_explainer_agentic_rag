"""FastAPI application entry point."""

import logging
import os
import sys
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from sqlalchemy import text

from .config import get_settings
from .api import router as api_router

settings = get_settings()
logger = logging.getLogger(__name__)

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[logging.StreamHandler(sys.stdout)]
)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan events with graceful shutdown."""
    # NOTE: Don't register custom signal handlers - uvicorn handles SIGINT/SIGTERM
    # and triggers this lifespan context manager's cleanup automatically

    # Startup
    logger.info(f"Starting {settings.app_name}...")

    # Initialize LangSmith tracing if configured
    if settings.langchain_tracing_v2:
        os.environ["LANGCHAIN_TRACING_V2"] = "true"
        if settings.langchain_api_key:
            os.environ["LANGCHAIN_API_KEY"] = settings.langchain_api_key
        os.environ["LANGCHAIN_PROJECT"] = settings.langchain_project
        logger.info(f"LangSmith tracing enabled for project: {settings.langchain_project}")
    elif settings.langsmith_tracing:
        os.environ["LANGSMITH_TRACING"] = "true"
        if settings.langsmith_api_key:
            os.environ["LANGSMITH_API_KEY"] = settings.langsmith_api_key
        logger.info("LangSmith tracing enabled via LANGSMITH_TRACING")

    yield

    # Shutdown - keep it fast
    import time
    start = time.time()
    logger.info("Initiating graceful shutdown...")

    # Close thread pool executor (don't wait - cancel in-flight requests)
    try:
        from .services.agent_service import _executor
        _executor.shutdown(wait=False, cancel_futures=True)
        logger.info(f"Thread pool shut down ({time.time() - start:.2f}s)")
    except Exception as e:
        logger.warning(f"Error shutting down thread pool: {e}")

    # Close Redis connections (rate limiters) - non-blocking
    try:
        from .services.rate_limiter import get_rate_limiter, get_global_rate_limiter
        rate_limiter = get_rate_limiter()
        if rate_limiter._redis:
            rate_limiter._redis.close()

        global_limiter = get_global_rate_limiter()
        if global_limiter._redis:
            global_limiter._redis.close()
        logger.info(f"Redis connections closed ({time.time() - start:.2f}s)")
    except Exception as e:
        logger.warning(f"Error closing Redis: {e}")

    # Close cache service Redis
    try:
        from .services.cache_service import get_cache_service
        cache = get_cache_service()
        if cache._redis:
            cache._redis.close()
    except Exception as e:
        logger.warning(f"Error closing cache Redis: {e}")

    # Dispose database engine
    try:
        from .database import engine
        await engine.dispose()
        logger.info(f"Database disposed ({time.time() - start:.2f}s)")
    except Exception as e:
        logger.warning(f"Error disposing database: {e}")

    # Skip checkpointer close - it's slow and not critical
    # The connection will be cleaned up by the OS

    logger.info(f"Shutdown complete ({time.time() - start:.2f}s)")


app = FastAPI(
    title=settings.app_name,
    description="Production-grade Agentic RAG System for Research Papers",
    version="0.1.0",
    lifespan=lifespan,
)

# CORS middleware - configured for production
_cors_origins = [
    "https://mlinterviewnotes.com",
    "https://www.mlinterviewnotes.com",
]
# Allow localhost in debug mode for development
if settings.debug:
    _cors_origins.extend([
        "http://localhost:3000",
        "http://localhost:5173",
        "http://127.0.0.1:3000",
        "http://127.0.0.1:5173",
    ])

app.add_middleware(
    CORSMiddleware,
    allow_origins=_cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Include API routes
app.include_router(api_router, prefix="/api/v1")


@app.get("/health")
async def health_check():
    """Comprehensive health check endpoint.

    Checks connectivity to all dependencies and returns appropriate status codes:
    - 200: All dependencies healthy
    - 503: One or more dependencies unhealthy (degraded mode)
    """
    from .database import AsyncSessionLocal
    from .services.rate_limiter import get_rate_limiter
    from qdrant_client import QdrantClient

    health = {
        "status": "healthy",
        "app": settings.app_name,
        "checks": {}
    }

    # Check PostgreSQL
    try:
        async with AsyncSessionLocal() as session:
            await session.execute(text("SELECT 1"))
        health["checks"]["postgres"] = "healthy"
    except Exception as e:
        health["checks"]["postgres"] = f"unhealthy: {str(e)}"
        health["status"] = "degraded"
        logger.error(f"PostgreSQL health check failed: {e}")

    # Check Redis (rate limiter)
    try:
        rate_limiter = get_rate_limiter()
        if rate_limiter.is_connected():
            health["checks"]["redis"] = "healthy"
        else:
            health["checks"]["redis"] = "unhealthy: not connected"
            health["status"] = "degraded"
    except Exception as e:
        health["checks"]["redis"] = f"unhealthy: {str(e)}"
        health["status"] = "degraded"
        logger.error(f"Redis health check failed: {e}")

    # Check Qdrant
    try:
        if settings.qdrant_url and settings.qdrant_api_key:
            client = QdrantClient(
                url=settings.qdrant_url,
                api_key=settings.qdrant_api_key,
                timeout=5,  # Quick timeout for health check
            )
            client.get_collections()
            health["checks"]["qdrant"] = "healthy"
        else:
            health["checks"]["qdrant"] = "not configured"
    except Exception as e:
        health["checks"]["qdrant"] = f"unhealthy: {str(e)}"
        health["status"] = "degraded"
        logger.error(f"Qdrant health check failed: {e}")

    status_code = 200 if health["status"] == "healthy" else 503
    return JSONResponse(content=health, status_code=status_code)


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("final_app.main:app", host="0.0.0.0", port=8000, reload=True)
