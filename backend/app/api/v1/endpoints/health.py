from fastapi import APIRouter

from app.schemas.health import HealthCheckResponse

router = APIRouter()


@router.get("/", response_model=HealthCheckResponse)
async def check_health() -> HealthCheckResponse:
    """Returns the application status details."""
    return HealthCheckResponse(status="healthy", service="ASM AI Agent", version="1.0.0")
