from app.database import get_db
from app.bootstrap import container
from app.context import ContextManager
from app.services.reporting_service import ReportingService


def get_reporting_service() -> ReportingService:
    """FastAPI dependency that resolves ReportingService from the application container.

    Returns:
        ReportingService: Singleton instance wired with the compiled agent graph.
    """
    return container.reporting_service


def get_context_manager() -> ContextManager:
    """FastAPI dependency that resolves the conversational context engine.

    Returns:
        ContextManager: Singleton instance backing conversational memory for
            follow-up resolution — the same instance ReportingService writes to.
    """
    return container.context_manager


# Central repository for FastAPI route dependency injections.
__all__ = ["get_db", "get_reporting_service", "get_context_manager"]
