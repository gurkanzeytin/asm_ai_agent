from fastapi import APIRouter

from app.api.v1.endpoints import context, health, reports

api_router = APIRouter()

# Register sub-routers
api_router.include_router(health.router, prefix="/health", tags=["health"])
api_router.include_router(reports.router, prefix="/report", tags=["report"])
api_router.include_router(context.router, prefix="/context", tags=["context"])
