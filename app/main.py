from fastapi import FastAPI
from app.core.config import settings
from app.api.v1.routes import api_router
from app.services.mcp_manager import mcp_manager
from contextlib import asynccontextmanager

@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup: Load MCP servers, initialize connections
    print("Starting up Agent Chassis...")
    await mcp_manager.load_servers()
    yield
    # Shutdown: Clean up resources
    print("Shutting down...")
    await mcp_manager.cleanup()

app = FastAPI(
    title=settings.PROJECT_NAME,
    openapi_url=f"{settings.API_V1_STR}/openapi.json",
    lifespan=lifespan
)

app.include_router(api_router, prefix=settings.API_V1_STR)

@app.get("/health")
async def health_check():
    return {"status": "healthy"}
