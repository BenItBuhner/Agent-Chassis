"""
Agent Chassis - FastAPI application entry point.

A modular, scalable foundation for building AI agents with:
- MCP (Model Context Protocol) integration
- Optional server-side session persistence (Redis + PostgreSQL)
- Streaming and non-streaming responses
- Tool calling capabilities
- Security hardening (CORS, headers, rate limiting)
"""

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.api.v1.routes import api_router
from app.core.config import settings
from app.services.mcp_manager import mcp_manager
from app.services.rate_limiter import rate_limit_middleware
from app.services.redis_cache import redis_cache

# Configure structured logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger("agent_chassis")


@asynccontextmanager
async def lifespan(app: FastAPI):
    """
    Application lifespan manager.

    Startup:
    - Load MCP servers
    - Optionally connect to Redis and PostgreSQL (if ENABLE_PERSISTENCE=true)

    Shutdown:
    - Clean up MCP connections
    - Close database connections
    """
    logger.info("Starting up Agent Chassis...")

    # Load MCP servers
    await mcp_manager.load_servers()

    # Conditionally connect persistence services
    if settings.ENABLE_PERSISTENCE:
        logger.info("Persistence enabled - connecting to storage services...")

        # Import here to avoid circular imports and allow optional usage
        from app.services.database import database

        # Connect Redis (fast cache) - using sanitized URL for logging
        redis_connected = await redis_cache.connect()
        if redis_connected:
            logger.info("Redis cache connected to %s", settings.sanitize_url(settings.REDIS_URL))
        else:
            logger.warning("Redis cache not available (continuing without cache)")

        # Connect PostgreSQL (durable storage)
        db_connected = await database.connect()
        if db_connected:
            logger.info("PostgreSQL database connected to %s", settings.sanitize_url(settings.DATABASE_URL))
        else:
            logger.warning("PostgreSQL database not available (continuing without database)")

        if not redis_connected and not db_connected:
            logger.error("ENABLE_PERSISTENCE is true but no storage services connected!")
    else:
        logger.info("Persistence disabled - using client-side message handling only")

    # Ensure Redis is available for rate limiting even if persistence is off
    if settings.ENABLE_RATE_LIMITING and not redis_cache.is_available:
        connected = await redis_cache.connect()
        if connected:
            logger.info("Redis connected for rate limiting at %s", settings.sanitize_url(settings.REDIS_URL))
        else:
            logger.error("Rate limiting enabled but Redis is unavailable")

    # Log security configuration status
    if settings.ENABLE_USER_AUTH:
        logger.info("User authentication ENABLED (JWT + OAuth)")
    if settings.CHASSIS_API_KEY:
        logger.info("API key authentication ENABLED")

    yield

    # Shutdown
    logger.info("Shutting down...")

    # Clean up MCP connections
    await mcp_manager.cleanup()

    # Clean up persistence connections if enabled
    if settings.ENABLE_PERSISTENCE:
        from app.services.database import database

        await redis_cache.close()
        await database.close()

    logger.info("Shutdown complete")


app = FastAPI(
    title=settings.PROJECT_NAME,
    description="A modular, scalable foundation for building AI agents with MCP integration",
    version="0.1.0",
    openapi_url=f"{settings.API_V1_STR}/openapi.json",
    lifespan=lifespan,
)

# =============================================================================
# Security Middleware
# =============================================================================

# CORS Middleware - Configure origins for production!
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.CORS_ORIGINS,
    allow_credentials=settings.CORS_ALLOW_CREDENTIALS,
    allow_methods=settings.CORS_ALLOW_METHODS,
    allow_headers=settings.CORS_ALLOW_HEADERS,
)


@app.middleware("http")
async def add_security_headers(request: Request, call_next):
    """
    Add security headers to all responses.

    Headers:
    - X-Content-Type-Options: Prevent MIME type sniffing
    - X-Frame-Options: Prevent clickjacking
    - X-XSS-Protection: Enable XSS filtering (legacy browsers)
    - Referrer-Policy: Control referrer information
    - Cache-Control: Prevent caching of sensitive data
    """
    response = await call_next(request)

    # Security headers
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["X-XSS-Protection"] = "1; mode=block"
    response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"

    # Prevent caching of API responses (they may contain sensitive data)
    if request.url.path.startswith(settings.API_V1_STR):
        response.headers["Cache-Control"] = "no-store, no-cache, must-revalidate, max-age=0"
        response.headers["Pragma"] = "no-cache"

    return response


# Rate limiting middleware (applies to API routes only)
app.middleware("http")(rate_limit_middleware)


@app.middleware("http")
async def catch_exceptions_middleware(request: Request, call_next):
    """
    Global exception handler to prevent internal error details leaking.

    Logs full exception for debugging, returns generic error to client.
    """
    try:
        return await call_next(request)
    except Exception:
        # Log full exception for debugging
        logger.exception("Unhandled exception during request to %s", request.url.path)

        # Return generic error to client (don't expose internals)
        return JSONResponse(
            status_code=500,
            content={"detail": "Internal server error"},
        )


# =============================================================================
# Routes
# =============================================================================

app.include_router(api_router, prefix=settings.API_V1_STR)


@app.get("/health")
async def health_check():
    """Health check endpoint for container orchestration."""
    health_status = {
        "status": "healthy",
        "persistence_enabled": settings.ENABLE_PERSISTENCE,
        "user_auth_enabled": settings.ENABLE_USER_AUTH,
    }

    if settings.ENABLE_PERSISTENCE:
        from app.services.database import database
        from app.services.redis_cache import redis_cache

        health_status["redis_connected"] = redis_cache.is_available
        health_status["database_connected"] = database.is_available

    return health_status
