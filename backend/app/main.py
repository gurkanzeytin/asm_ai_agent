import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.v1.api import api_router
from app.api.exception_handlers import EXCEPTION_HANDLERS
from app.core.config import settings
from app.core.logging import setup_logging
from app.schemas.health import HealthCheckResponse

# Configure logs prior to app bootstrapping
setup_logging()
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Lifecycle event context manager handling application startup and shutdown events."""
    logger.info(f"Starting application: {settings.APP_NAME}")
    logger.info(f"Environment: {settings.ENVIRONMENT}")
    logger.info(f"Version: {settings.APP_VERSION}")

    # Log environment settings safely
    gemini_key_present = "PRESENT" if settings.GEMINI_API_KEY else "MISSING"
    logger.info(
        "\n================ Environment Diagnostics ================\n"
        f"LLM_PROVIDER : {settings.LLM_PROVIDER}\n"
        f"GEMINI_MODEL : {settings.GEMINI_MODEL}\n"
        f"API KEY      : {gemini_key_present}\n"
        f"OLLAMA_MODEL : {settings.OLLAMA_MODEL}\n"
        "========================================================="
    )

    yield
    logger.info(f"Shutting down application: {settings.APP_NAME}")


app = FastAPI(
    title=settings.APP_NAME,
    version=settings.APP_VERSION,
    description="AI Reporting Agent Backend",
    openapi_url=f"{settings.API_V1_PREFIX}/openapi.json",
    lifespan=lifespan,
    debug=settings.DEBUG,
)

# CORS middleware — must be registered before any route or exception handler
# to ensure OPTIONS preflight requests are handled correctly.
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.ALLOWED_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Register domain exception → HTTP status code handlers
for exc_class, handler in EXCEPTION_HANDLERS:
    app.add_exception_handler(exc_class, handler)


# Root endpoint "/"
@app.get("/", tags=["root"])
async def root() -> dict[str, str]:
    """Root endpoint returning basic API details."""
    return {"message": "ASM AI Agent API"}


# Root health check endpoint "/health"
@app.get("/health", response_model=HealthCheckResponse, tags=["healthcheck"])
async def health() -> HealthCheckResponse:
    """Returns application health status."""
    return HealthCheckResponse(
        status="healthy",
        service=settings.APP_NAME,
        version=settings.APP_VERSION,
    )


# Mount the version 1 API router
app.include_router(api_router, prefix=settings.API_V1_PREFIX)

if __name__ == "__main__":
    import uvicorn

    # Local run hook
    uvicorn.run("app.main:app", host="0.0.0.0", port=8000, reload=settings.DEBUG)
