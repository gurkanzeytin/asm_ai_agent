from app.database import get_db
from app.bootstrap import container
from app.services.reporting_service import ReportingService


def get_reporting_service() -> ReportingService:
    """FastAPI dependency that resolves ReportingService from the application container.

    Returns:
        ReportingService: Singleton instance wired with the compiled agent graph.
    """
    return container.reporting_service


# Central repository for FastAPI route dependency injections.
__all__ = ["get_db", "get_reporting_service"]
