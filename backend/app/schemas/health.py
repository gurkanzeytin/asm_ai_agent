from pydantic import BaseModel, Field


class HealthCheckResponse(BaseModel):
    """Pydantic schema representing status diagnostic payloads."""

    status: str = Field(default="healthy", description="Application status check.")
    service: str = Field(default="ASM AI Agent", description="The service name.")
    version: str = Field(default="1.0.0", description="API current version.")
