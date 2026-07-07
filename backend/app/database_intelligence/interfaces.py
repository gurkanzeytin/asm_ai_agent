from abc import ABC, abstractmethod

from app.database_intelligence.models import DatabaseContext, DatabaseSchema


class IDatabaseInspector(ABC):
    """Abstract interface representing a database inspector.

    Isolates dialect-specific inspection logic from the rest of the application.
    """

    @abstractmethod
    async def inspect_schema(self) -> DatabaseSchema:
        """Inspects database schemas and builds a strongly-typed DatabaseSchema metadata model.

        Returns:
            DatabaseSchema: Discovered database tables, views, and statistics.
        """
        pass


class ISchemaRetriever(ABC):
    """Abstract interface representing a schema retriever.

    Supports keyword, semantic, or hybrid filtering strategies to return relevant
    database metadata for a specific query without coupling callers to retrieval details.
    """

    @abstractmethod
    def retrieve_context(self, question: str, schema: DatabaseSchema) -> DatabaseContext:
        """Analyzes a question and retrieves the relevant tables/views schema metadata.

        Args:
            question: The user query context.
            schema: Discovered database schema metadata index.

        Returns:
            DatabaseContext: Structured Pydantic model containing relevant tables/views.
        """
        pass
