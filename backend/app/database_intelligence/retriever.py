import logging
import re
import unicodedata
import asyncio
import time
import concurrent.futures
from typing import List, Set, Tuple, Dict, Optional

from app.core.config import settings
from app.database_intelligence.exceptions import SchemaRetrievalError
from app.database_intelligence.interfaces import ISchemaRetriever
from app.database_intelligence.models import (
    ColumnMetadata,
    DatabaseContext,
    DatabaseSchema,
    TableMetadata,
    ViewMetadata,
    ForeignKeyMetadata,
)
from app.database_intelligence.synonyms import SYNONYM_MAP

logger = logging.getLogger(__name__)


def _normalize(text: str) -> str:
    """Strips Turkish and other diacritics by decomposing unicode characters.

    Converts 'ş' → 's', 'ç' → 'c', 'ğ' → 'g', 'ı' → 'i', 'ö' → 'o', 'ü' → 'u'.
    Applied to both query tokens and schema names so matching is diacritic-insensitive.
    """
    nfkd = unicodedata.normalize("NFKD", text)
    return "".join(c for c in nfkd if not unicodedata.combining(c))


def run_coroutine_sync(coro):
    """Helper to run a coroutine synchronously, handling running event loops in FastAPI."""
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        loop = None

    if loop and loop.is_running():
        with concurrent.futures.ThreadPoolExecutor(max_workers=1) as executor:
            future = executor.submit(asyncio.run, coro)
            return future.result()
    else:
        return asyncio.run(coro)


class SchemaRetriever(ISchemaRetriever):
    """Relationship-aware semantic context retriever for database schemas.

    Combines semantic search, keyword boosting, BFS foreign-key graph traversal,
    lightweight neighborhood diversity penalty, and token budget selection.
    """

    def __init__(
        self,
        schema_cache=None,
        match_threshold: float = 0.3,
        token_budget: Optional[int] = None,
        max_columns_per_table: Optional[int] = None,
        max_tables: Optional[int] = None,
        max_depth: Optional[int] = None,
    ):
        self.schema_cache = schema_cache
        self.match_threshold = match_threshold
        self.token_budget = token_budget if token_budget is not None else getattr(settings, "SCHEMA_TOKEN_BUDGET", 1500)
        self.max_columns_per_table = (
            max_columns_per_table if max_columns_per_table is not None else getattr(settings, "SCHEMA_MAX_COLUMNS", 15)
        )
        self.max_tables = max_tables if max_tables is not None else getattr(settings, "SCHEMA_MAX_TABLES", 5)
        self.max_depth = max_depth if max_depth is not None else getattr(settings, "SCHEMA_GRAPH_MAX_DEPTH", 2)

    def retrieve_context(self, question: str, schema: DatabaseSchema) -> DatabaseContext:
        """Retrieves and ranks relevant table and view structures matching the user query."""
        return run_coroutine_sync(self._retrieve_context_async(question, schema))

    async def _retrieve_context_async(self, question: str, schema: DatabaseSchema) -> DatabaseContext:
        """Asynchronously processes retrieval within a single event loop context."""
        start_time = time.perf_counter()
        logger.info(f"Filtering schema context matching query: '{question}'")
        try:
            # 1. Retrieve or build graph and semantic index
            graph = None
            index = None
            if self.schema_cache:
                graph = await self.schema_cache.get_graph()
                index = await self.schema_cache.get_index()

            # Fallback if cache retrieval fails or is not provided
            if graph is None:
                from app.database_intelligence.schema_graph import SchemaGraph
                graph = SchemaGraph(schema)
            if index is None:
                from app.database_intelligence.schema_embeddings import SemanticSchemaIndex
                from app.llm.provider import LLMFactory
                llm_provider = LLMFactory.get_provider()
                index = SemanticSchemaIndex(schema, llm_provider)
                await index.build_index()

            # 2. Semantic search top tables
            semantic_matches = await index.search(question, k=len(schema.tables))
            semantic_scores = {name: score for name, score in semantic_matches}

            # 3. Keyword confidence boost
            query_tokens = self._tokenize_and_expand(question)

            # Match directly scored tables using keyword overlap
            matched_tables: Set[str] = set()
            keyword_scores: Dict[str, float] = {}
            for table_name, table in schema.tables.items():
                kw_score = self._score_table(query_tokens, table)
                normalized_kw = min(1.0, kw_score / 10.0)
                keyword_scores[table_name] = normalized_kw

                # Check if matches threshold
                sem_score = semantic_scores.get(table_name, 0.0)
                kw_threshold = self.match_threshold if self.match_threshold >= 1.0 else 1.0
                if sem_score >= 0.3 or kw_score >= kw_threshold:
                    matched_tables.add(table_name)

            # 4. BFS Traversal for Foreign Key Expansion (Multi-Hop)
            # Maps table name to (parent table name, path distance)
            expanded_tables: Dict[str, Tuple[str, int]] = {}
            queue = []

            # Populate queue with directly matched nodes
            for table_name in matched_tables:
                queue.append((table_name, 0))

            while queue:
                current_node, dist = queue.pop(0)
                if dist >= self.max_depth:
                    continue

                neighbors = graph.get_neighbors(current_node)
                for neighbor in neighbors:
                    if neighbor not in matched_tables and neighbor not in expanded_tables:
                        expanded_tables[neighbor] = (current_node, dist + 1)
                        queue.append((neighbor, dist + 1))

            # 5. Centrality Scoring (degree-based)
            max_degree = max([len(node.neighbors) for node in graph.nodes.values()] or [1])
            if max_degree == 0:
                max_degree = 1
            node_centralities = {}
            for name, node in graph.nodes.items():
                node_centralities[name] = len(node.neighbors) / max_degree

            # Build Candidates List
            # Structure: [table_name, score, direct_matched_bool, parent_name, distance]
            candidates: List[List] = []

            # Score direct matches
            for name in matched_tables:
                sem = semantic_scores.get(name, 0.0)
                kw = keyword_scores.get(name, 0.0)
                cent = node_centralities.get(name, 0.0)

                score = (sem * 0.7) + (kw * 0.3) + (0.1 * cent)
                candidates.append([name, score, True, None, 0])

            # Score expanded nodes with exponential distance decay
            for name, (parent, dist) in expanded_tables.items():
                cent = node_centralities.get(name, 0.0)

                parent_sem = semantic_scores.get(parent, 0.0)
                parent_kw = keyword_scores.get(parent, 0.0)
                parent_cent = node_centralities.get(parent, 0.0)
                parent_score = (parent_sem * 0.7) + (parent_kw * 0.3) + (0.1 * parent_cent)

                decay = 0.5 ** dist
                score = (decay * parent_score) + (0.1 * cent)
                candidates.append([name, score, False, parent, dist])

            # 6. Budget Selection & Neighborhood Diversity Penalty Loop
            selected_tables: List[TableMetadata] = []
            current_tokens = 0
            ranking_details = []

            # Sort initial candidate preview details
            initial_candidates = sorted(candidates, key=lambda x: x[1], reverse=True)

            while candidates:
                # Sort candidates dynamically by active score descending
                candidates.sort(key=lambda x: x[1], reverse=True)
                top_cand = candidates.pop(0)

                name, score, is_matched, parent, dist = top_cand
                table = schema.tables[name]
                capped_table = self._cap_table_columns(table)
                table_text = self._format_table_raw(capped_table)
                table_tokens = len(table_text) // 4

                # Check table count limit (self.max_tables) for backward compatibility
                if self.max_tables is not None and len(selected_tables) >= self.max_tables:
                    break

                # Apply token budget criteria
                if not selected_tables or (current_tokens + table_tokens <= self.token_budget):
                    selected_tables.append(capped_table)
                    current_tokens += table_tokens

                    # Log candidate scoring breakdown
                    sem = semantic_scores.get(name, 0.0)
                    kw = keyword_scores.get(name, 0.0)
                    cent = node_centralities.get(name, 0.0)
                    
                    if is_matched:
                        detail = (
                            f"Table: {name} (DIRECT MATCH)\n"
                            f"  - Semantic Similarity : {sem:.4f}\n"
                            f"  - Keyword Overlap     : {kw:.4f}\n"
                            f"  - Centrality Score    : {cent:.4f}\n"
                            f"  - Final Score         : {score:.4f}"
                        )
                    else:
                        detail = (
                            f"Table: {name} (EXPANDED via '{parent}', distance={dist})\n"
                            f"  - Semantic Similarity : {sem:.4f}\n"
                            f"  - Keyword Overlap     : {kw:.4f}\n"
                            f"  - Centrality Score    : {cent:.4f}\n"
                            f"  - Distance Decay      : {0.5**dist:.4f}\n"
                            f"  - Final Score         : {score:.4f}"
                        )
                    ranking_details.append(detail)

                    # Dynamic Diversity step: penalize remaining candidates that are immediate neighbors
                    neighbors = graph.get_neighbors(name)
                    for c in candidates:
                        c_name = c[0]
                        if c_name in neighbors:
                            # Apply penalty of 0.7
                            c[1] = c[1] * 0.7
                else:
                    break

            # Fallback: if no tables matched at all, select all tables capped by max_tables and token budget
            if not selected_tables:
                logger.warning("No tables matched query. Applying fallback schema context.")
                all_tables = sorted(list(schema.tables.values()), key=lambda x: x.name)
                for table in all_tables:
                    capped_table = self._cap_table_columns(table)
                    table_text = self._format_table_raw(capped_table)
                    table_tokens = len(table_text) // 4

                    if self.max_tables is not None and len(selected_tables) >= self.max_tables:
                        break

                    if not selected_tables or (current_tokens + table_tokens <= self.token_budget):
                        selected_tables.append(capped_table)
                        current_tokens += table_tokens
                    else:
                        break

            # 7. Views Selection (Fallback to legacy keyword matching for views)
            scored_views = []
            for view_name, view in schema.views.items():
                view_score = self._score_view(query_tokens, view)
                if view_score > 0:
                    scored_views.append((view_score, view))
            scored_views.sort(key=lambda x: x[0], reverse=True)
            selected_views = [v for _, v in scored_views]

            # 8. Observability Diagnostics Logging
            elapsed_ms = (time.perf_counter() - start_time) * 1000

            logger.info(
                "\nSchema Ranking Details\n======================\n" +
                "\n\n".join(ranking_details) +
                f"\n\nPrompt Budget Utilization\n-------------------------\n{current_tokens} / {self.token_budget} tokens"
            )

            # High-level Retrieval Quality Metrics
            logger.info(
                "Completed database schema retrieval.",
                extra={
                    "semantic_candidates_count": len(matched_tables),
                    "expanded_tables_count": len(expanded_tables),
                    "selected_tables_count": len(selected_tables),
                    "prompt_tokens_estimated": current_tokens,
                    "duration_ms": elapsed_ms,
                    "matched_tables": [t.name for t in selected_tables],
                    "matched_views": [v.name for v in selected_views],
                },
            )

            return DatabaseContext(tables=selected_tables, views=selected_views)

        except Exception as e:
            logger.error(f"Error during schema context retrieval: {e}")
            raise SchemaRetrievalError(f"Failed to retrieve database context: {e}") from e

    # ── Token helpers ──────────────────────────────────────────────────────────

    def _tokenize(self, text: str) -> Set[str]:
        """Tokenizes text into a set of lowercased, diacritic-normalized alphanumeric words."""
        normalized = _normalize(text.lower())
        return set(re.findall(r"\w+", normalized))

    def _tokenize_and_expand(self, question: str) -> Set[str]:
        """Tokenizes the question and expands tokens with synonym translations."""
        base_tokens = self._tokenize(question)
        expanded: Set[str] = set(base_tokens)
        for token in base_tokens:
            if token in SYNONYM_MAP:
                expanded.update(SYNONYM_MAP[token])
        return expanded

    # ── Column Capping Helper ──────────────────────────────────────────────────

    def _cap_table_columns(self, table: TableMetadata) -> TableMetadata:
        """Returns a copy of the table with columns capped to max_columns_per_table."""
        if len(table.columns) <= self.max_columns_per_table:
            return table

        # Collect names of PK and FK columns — these are always kept
        pk_names: Set[str] = set(table.primary_keys)
        fk_names: Set[str] = {
            col for fk in table.foreign_keys for col in fk.constrained_columns
        }
        priority_names = pk_names | fk_names

        priority_cols = [c for c in table.columns if c.name in priority_names]
        other_cols = [c for c in table.columns if c.name not in priority_names]

        remaining_slots = max(0, self.max_columns_per_table - len(priority_cols))
        selected = priority_cols + other_cols[:remaining_slots]

        return table.model_copy(update={"columns": selected})

    def _format_table_raw(self, table: TableMetadata) -> str:
        """Helper to format a single table metadata model into its prompt representation."""
        lines = [f"Table: {table.name}"]
        cols = [
            f"{col.name} ({col.type_name}){' [PK]' if col.primary_key else ''}"
            for col in table.columns
        ]
        lines.append(f"  Columns: {', '.join(cols)}")
        if table.foreign_keys:
            fks = [
                f"({', '.join(fk.constrained_columns)})->{fk.referred_table}({', '.join(fk.referred_columns)})"
                for fk in table.foreign_keys
            ]
            lines.append(f"  Foreign Keys: {', '.join(fks)}")
        return "\n".join(lines)

    # ── Scoring Helpers ────────────────────────────────────────────────────────

    def _score_table(self, query_tokens: Set[str], table: TableMetadata) -> int:
        """Scores a table metadata object based on intersection with query tokens."""
        score = 0

        # Match table name words (normalized)
        table_words = self._tokenize(table.name)
        score += len(query_tokens.intersection(table_words)) * 10

        # Match column words (normalized)
        for col in table.columns:
            col_words = self._tokenize(col.name)
            score += len(query_tokens.intersection(col_words)) * 2

            if col.comment:
                comment_words = self._tokenize(col.comment)
                score += len(query_tokens.intersection(comment_words)) * 1

        # Match table comment words (normalized)
        if table.comment:
            comment_words = self._tokenize(table.comment)
            score += len(query_tokens.intersection(comment_words)) * 1

        return score

    def _score_view(self, query_tokens: Set[str], view: ViewMetadata) -> int:
        """Scores a view metadata object based on intersection with query tokens."""
        score = 0

        # Match view name words (normalized)
        view_words = self._tokenize(view.name)
        score += len(query_tokens.intersection(view_words)) * 10

        # Match view comment words (normalized)
        if view.comment:
            comment_words = self._tokenize(view.comment)
            score += len(query_tokens.intersection(comment_words)) * 1

        return score
