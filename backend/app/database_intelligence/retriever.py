import asyncio
import concurrent.futures
import logging
import re
import time
import unicodedata

from app.core.config import settings
from app.database_intelligence.exceptions import SchemaRetrievalError
from app.database_intelligence.interfaces import ISchemaRetriever
from app.database_intelligence.models import (
    DatabaseContext,
    DatabaseSchema,
    TableMetadata,
    ViewMetadata,
)
from app.database_intelligence.synonyms import SYNONYM_MAP
from app.services.query_analyzer import QueryAnalyzer

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
        token_budget: int | None = None,
        max_columns_per_table: int | None = None,
        max_tables: int | None = None,
        max_depth: int | None = None,
        query_analyzer: QueryAnalyzer | None = None,
    ):
        self.schema_cache = schema_cache
        self.match_threshold = match_threshold
        self.token_budget = (
            token_budget
            if token_budget is not None
            else getattr(settings, "SCHEMA_TOKEN_BUDGET", 1500)
        )
        self.max_columns_per_table = (
            max_columns_per_table
            if max_columns_per_table is not None
            else getattr(settings, "SCHEMA_MAX_COLUMNS", 15)
        )
        self.max_tables = (
            max_tables
            if max_tables is not None
            else getattr(settings, "SCHEMA_MAX_TABLES", 5)
        )
        self.max_depth = (
            max_depth
            if max_depth is not None
            else getattr(settings, "SCHEMA_GRAPH_MAX_DEPTH", 2)
        )
        self.query_analyzer = query_analyzer or QueryAnalyzer()

    def retrieve_context(self, question: str, schema: DatabaseSchema) -> DatabaseContext:
        """Retrieves and ranks relevant table and view structures matching the user query."""
        return run_coroutine_sync(self._retrieve_context_async(question, schema))

    async def _retrieve_context_async(
        self,
        question: str,
        schema: DatabaseSchema,
    ) -> DatabaseContext:
        """Asynchronously processes retrieval within a single event loop context."""
        start_time = time.perf_counter()
        logger.info(f"Filtering schema context matching query: '{question}'")
        try:
            query_analysis = self.query_analyzer.analyze(question)
            retrieval_query = query_analysis.normalized_query
            query_analysis_ms = (time.perf_counter() - start_time) * 1000

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
            semantic_start = time.perf_counter()
            semantic_matches = await index.search(retrieval_query, k=len(schema.tables))
            semantic_search_ms = (time.perf_counter() - semantic_start) * 1000
            embedding_error = getattr(index, "last_embedding_error", None)
            if embedding_error:
                logger.error(
                    "Semantic retrieval embedding failed; continuing with hash fallback "
                    "diagnostics.",
                    extra={
                        "embedding_model": embedding_error.get("embedding_model"),
                        "endpoint": embedding_error.get("endpoint"),
                        "http_status": embedding_error.get("http_status"),
                        "response_body": embedding_error.get("response_body"),
                        "exception": embedding_error.get("exception"),
                        "duration_ms": embedding_error.get("duration_ms"),
                    },
                )
            semantic_scores = {name: score for name, score in semantic_matches}

            # 3. Keyword confidence boost
            ranking_start = time.perf_counter()
            query_tokens = self._tokenize_and_expand(retrieval_query)
            entity_tokens = self._entity_tokens(query_analysis)
            entity_table_names = self._entity_table_names(query_analysis, schema)

            # Match directly scored tables using keyword overlap
            matched_tables: set[str] = set()
            keyword_scores: dict[str, float] = {}
            entity_scores: dict[str, float] = {}
            for table_name, table in schema.tables.items():
                kw_score = self._score_table(query_tokens, table)
                normalized_kw = min(1.0, kw_score / 10.0)
                keyword_scores[table_name] = normalized_kw
                entity_score = min(1.0, self._score_table(entity_tokens, table) / 10.0)
                entity_score = max(
                    entity_score,
                    self._relationship_entity_score(table_name, table, entity_table_names),
                )
                entity_scores[table_name] = entity_score

                # Check if matches threshold
                sem_score = semantic_scores.get(table_name, 0.0)
                kw_threshold = self.match_threshold if self.match_threshold >= 1.0 else 1.0
                if (
                    sem_score >= 0.3
                    or kw_score >= kw_threshold
                    or entity_score > 0
                    or table_name in entity_table_names
                ):
                    matched_tables.add(table_name)

            # 4. BFS Traversal for Foreign Key Expansion (Multi-Hop)
            # Maps table name to (parent table name, path distance)
            expanded_tables: dict[str, tuple[str, int]] = {}
            queue = []
            graph_start = time.perf_counter()

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
            graph_traversal_ms = (time.perf_counter() - graph_start) * 1000

            # 5. Centrality Scoring (degree-based)
            max_degree = max([len(node.neighbors) for node in graph.nodes.values()] or [1])
            if max_degree == 0:
                max_degree = 1
            node_centralities = {}
            for name, node in graph.nodes.items():
                node_centralities[name] = len(node.neighbors) / max_degree

            # Build Candidates List
            # Structure: [table_name, score, direct_matched_bool, parent_name, distance]
            candidates: list[list] = []

            # Score direct matches
            for name in matched_tables:
                sem = semantic_scores.get(name, 0.0)
                kw = keyword_scores.get(name, 0.0)
                ent = entity_scores.get(name, 0.0)
                cent = node_centralities.get(name, 0.0)

                score = (sem * 0.7) + (kw * 0.3) + (ent * 0.2) + (0.1 * cent)
                candidates.append([name, score, True, None, 0])

            # Score expanded nodes with exponential distance decay
            for name, (parent, dist) in expanded_tables.items():
                cent = node_centralities.get(name, 0.0)

                parent_sem = semantic_scores.get(parent, 0.0)
                parent_kw = keyword_scores.get(parent, 0.0)
                parent_ent = entity_scores.get(parent, 0.0)
                parent_cent = node_centralities.get(parent, 0.0)
                parent_score = (
                    (parent_sem * 0.7)
                    + (parent_kw * 0.3)
                    + (parent_ent * 0.2)
                    + (0.1 * parent_cent)
                )

                decay = 0.5 ** dist
                score = (decay * parent_score) + (0.1 * cent)
                candidates.append([name, score, False, parent, dist])

            # 6. Budget Selection & Neighborhood Diversity Penalty Loop
            selected_tables: list[TableMetadata] = []
            current_tokens = 0
            ranking_details = []

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
                    ent = entity_scores.get(name, 0.0)
                    cent = node_centralities.get(name, 0.0)

                    if is_matched:
                        detail = (
                            f"Table: {name} (DIRECT MATCH)\n"
                            f"  - Semantic Similarity : {sem:.4f}\n"
                            f"  - Keyword Overlap     : {kw:.4f}\n"
                            f"  - Entity Boost        : {ent:.4f}\n"
                            f"  - Centrality Score    : {cent:.4f}\n"
                            f"  - Final Score         : {score:.4f}"
                        )
                    else:
                        detail = (
                            f"Table: {name} (EXPANDED via '{parent}', distance={dist})\n"
                            f"  - Semantic Similarity : {sem:.4f}\n"
                            f"  - Keyword Overlap     : {kw:.4f}\n"
                            f"  - Entity Boost        : {ent:.4f}\n"
                            f"  - Centrality Score    : {cent:.4f}\n"
                            f"  - Distance Decay      : {0.5**dist:.4f}\n"
                            f"  - Final Score         : {score:.4f}"
                        )
                    ranking_details.append(detail)

                    # Dynamic Diversity step: penalize remaining immediate neighbors.
                    neighbors = graph.get_neighbors(name)
                    for c in candidates:
                        c_name = c[0]
                        if c_name in neighbors:
                            # Apply penalty of 0.7
                            c[1] = c[1] * 0.7
                else:
                    break

            # Fallback: if no tables matched, select capped tables by budget.
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
            for _view_name, view in schema.views.items():
                view_score = self._score_view(query_tokens, view)
                if view_score > 0:
                    scored_views.append((view_score, view))
            scored_views.sort(key=lambda x: x[0], reverse=True)
            selected_views = [v for _, v in scored_views]
            ranking_ms = (time.perf_counter() - ranking_start) * 1000

            # 8. Observability Diagnostics Logging
            elapsed_ms = (time.perf_counter() - start_time) * 1000

            logger.info(
                "\nSchema Ranking Details\n======================\n"
                + "\n\n".join(ranking_details)
                + "\n\nPrompt Budget Utilization\n-------------------------\n"
                + f"{current_tokens} / {self.token_budget} tokens"
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
                    "query_analysis_ms": query_analysis_ms,
                    "semantic_search_ms": semantic_search_ms,
                    "graph_traversal_ms": graph_traversal_ms,
                    "ranking_ms": ranking_ms,
                    "original_query": query_analysis.original_query,
                    "normalized_query": query_analysis.normalized_query,
                    "detected_entities": [entity.entity_type for entity in query_analysis.entities],
                    "matched_tables": [t.name for t in selected_tables],
                    "matched_views": [v.name for v in selected_views],
                },
            )
            logger.info(
                "Schema retrieval performance profile.",
                extra={
                    "query_analysis_ms": query_analysis_ms,
                    "semantic_search_ms": semantic_search_ms,
                    "graph_traversal_ms": graph_traversal_ms,
                    "ranking_ms": ranking_ms,
                    "total_ms": elapsed_ms,
                    "semantic_candidates_count": len(matched_tables),
                    "expanded_tables_count": len(expanded_tables),
                    "selected_tables_count": len(selected_tables),
                },
            )

            return DatabaseContext(
                tables=selected_tables,
                views=selected_views,
                # final_query has relative dates resolved to explicit ISO ranges;
                # it is the single source of truth handed to SQL generation.
                normalized_query=query_analysis.final_query or query_analysis.normalized_query,
            )

        except Exception as e:
            logger.error(f"Error during schema context retrieval: {e}")
            raise SchemaRetrievalError(f"Failed to retrieve database context: {e}") from e

    # ── Token helpers ──────────────────────────────────────────────────────────

    def _tokenize(self, text: str) -> set[str]:
        """Tokenizes text into a set of lowercased, diacritic-normalized alphanumeric words."""
        normalized = _normalize(text.lower())
        return set(re.findall(r"\w+", normalized))

    def _tokenize_and_expand(self, question: str) -> set[str]:
        """Tokenizes the question and expands tokens with synonym translations."""
        base_tokens = self._tokenize(question)
        expanded: set[str] = set(base_tokens)
        for token in base_tokens:
            if token in SYNONYM_MAP:
                expanded.update(SYNONYM_MAP[token])
        return expanded

    def _entity_tokens(self, query_analysis) -> set[str]:
        """Builds token set from detected NLU entities for additive schema ranking boost."""
        tokens: set[str] = set()
        for entity in query_analysis.entities:
            tokens.update(self._tokenize(entity.entity_type))
            tokens.update(self._tokenize(entity.canonical))
            tokens.update(self._tokenize(entity.normalized_text))
            tokens.update(SYNONYM_MAP.get(entity.canonical, []))
        return tokens

    def _entity_table_names(self, query_analysis, schema: DatabaseSchema) -> set[str]:
        """Finds schema tables that directly represent detected business entities."""
        names: set[str] = set()
        for entity in query_analysis.entities:
            entity_tokens = set()
            entity_tokens.update(self._tokenize(entity.entity_type))
            entity_tokens.update(self._tokenize(entity.canonical))
            entity_tokens.update(self._tokenize(entity.normalized_text))
            entity_tokens.update(SYNONYM_MAP.get(entity.canonical, []))

            for table_name in schema.tables:
                table_tokens = self._tokenize(table_name)
                normalized_name = _normalize(table_name.lower())
                if table_tokens.intersection(entity_tokens) or any(
                    normalized_name in self._entity_table_variants(token)
                    for token in entity_tokens
                ):
                    names.add(table_name)
        return names

    def _entity_table_variants(self, token: str) -> set[str]:
        return {
            token,
            f"{token}lar",
            f"{token}ler",
        }

    def _relationship_entity_score(
        self,
        table_name: str,
        table: TableMetadata,
        entity_table_names: set[str],
    ) -> float:
        if not entity_table_names:
            return 0.0
        if table_name in entity_table_names:
            return 8.0 if self._has_descriptive_column(table) else 5.0
        referred_tables = {fk.referred_table for fk in table.foreign_keys}
        referred_entity_count = len(referred_tables.intersection(entity_table_names))
        if referred_entity_count >= 2:
            return 4.5
        if referred_entity_count == 1:
            return 2.0
        return 0.0

    def _has_descriptive_column(self, table: TableMetadata) -> bool:
        descriptive_markers = (
            "ad",
            "adi",
            "ad_soyad",
            "name",
            "title",
            "unvan",
            "sirket_adi",
            "bolum_adi",
            "test_adi",
        )
        for column in table.columns:
            normalized = _normalize(column.name.lower())
            if normalized in descriptive_markers or normalized.endswith("_adi"):
                return True
        return False

    # ── Column Capping Helper ──────────────────────────────────────────────────

    def _cap_table_columns(self, table: TableMetadata) -> TableMetadata:
        """Returns a copy of the table with columns capped to max_columns_per_table."""
        if len(table.columns) <= self.max_columns_per_table:
            return table

        # Collect names of PK and FK columns — these are always kept
        pk_names: set[str] = set(table.primary_keys)
        fk_names: set[str] = {
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
                f"({', '.join(fk.constrained_columns)})->"
                f"{fk.referred_table}({', '.join(fk.referred_columns)})"
                for fk in table.foreign_keys
            ]
            lines.append(f"  Foreign Keys: {', '.join(fks)}")
        return "\n".join(lines)

    # ── Scoring Helpers ────────────────────────────────────────────────────────

    def _score_table(self, query_tokens: set[str], table: TableMetadata) -> int:
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

    def _score_view(self, query_tokens: set[str], view: ViewMetadata) -> int:
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
