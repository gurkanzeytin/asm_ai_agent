import logging
import re
from typing import List, Set

from app.database_intelligence.exceptions import SchemaRetrievalError
from app.database_intelligence.interfaces import ISchemaRetriever
from app.database_intelligence.models import (
    DatabaseContext,
    DatabaseSchema,
    TableMetadata,
    ViewMetadata,
)

logger = logging.getLogger(__name__)


class SchemaRetriever(ISchemaRetriever):
    """Keyword-based context retriever filtering relevant metadata models.

    Identifies table and view constraints matching user query keywords and returns
    a structured DatabaseContext model.
    """

    def __init__(self, match_threshold: int = 1):
        self.match_threshold = match_threshold

    def retrieve_context(self, question: str, schema: DatabaseSchema) -> DatabaseContext:
        """Retrieves and ranks relevant table and view structures matching query keywords."""
        logger.info(f"Filtering schema context matching query: '{question}'")
        try:
            tokens = self._tokenize(question)
            if not tokens:
                logger.warning("Empty tokenized search parameters. Returning empty DatabaseContext.")
                return DatabaseContext(tables=[], views=[])

            # Raking Tables
            scored_tables = []
            for table_name, table in schema.tables.items():
                score = self._score_table(tokens, table)
                if score >= self.match_threshold:
                    scored_tables.append((score, table))
            scored_tables.sort(key=lambda x: x[0], reverse=True)

            # Ranking Views
            scored_views = []
            for view_name, view in schema.views.items():
                score = self._score_view(tokens, view)
                if score >= self.match_threshold:
                    scored_views.append((score, view))
            scored_views.sort(key=lambda x: x[0], reverse=True)

            matched_tables = [t for _, t in scored_tables]
            matched_views = [v for _, v in scored_views]

            logger.info(
                "Completed database schema retrieval.",
                extra={
                    "matched_tables_count": len(matched_tables),
                    "matched_views_count": len(matched_views),
                    "matched_tables": [t.name for t in matched_tables],
                    "matched_views": [v.name for v in matched_views],
                },
            )

            return DatabaseContext(tables=matched_tables, views=matched_views)

        except Exception as e:
            logger.error(f"Error during schema context retrieval: {e}")
            raise SchemaRetrievalError(f"Failed to retrieve database context: {e}") from e

    def _tokenize(self, text: str) -> Set[str]:
        """Tokenizes text into a set of lowercased alphanumeric words."""
        return set(re.findall(r"\w+", text.lower()))

    def _score_table(self, query_tokens: Set[str], table: TableMetadata) -> int:
        """Scores a table metadata object based on intersection with query tokens."""
        score = 0

        # Match table name words
        table_words = self._tokenize(table.name)
        score += len(query_tokens.intersection(table_words)) * 10

        # Match column words
        for col in table.columns:
            col_words = self._tokenize(col.name)
            score += len(query_tokens.intersection(col_words)) * 2

            if col.comment:
                comment_words = self._tokenize(col.comment)
                score += len(query_tokens.intersection(comment_words)) * 1

        # Match table comments words
        if table.comment:
            comment_words = self._tokenize(table.comment)
            score += len(query_tokens.intersection(comment_words)) * 1

        return score

    def _score_view(self, query_tokens: Set[str], view: ViewMetadata) -> int:
        """Scores a view metadata object based on intersection with query tokens."""
        score = 0

        # Match view name words
        view_words = self._tokenize(view.name)
        score += len(query_tokens.intersection(view_words)) * 10

        # Match view comment words
        if view.comment:
            comment_words = self._tokenize(view.comment)
            score += len(query_tokens.intersection(comment_words)) * 1

        return score
