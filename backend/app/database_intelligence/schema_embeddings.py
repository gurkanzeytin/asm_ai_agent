import hashlib
import json
import logging
import os

import faiss
import numpy as np

from app.database_intelligence.models import DatabaseSchema, TableMetadata
from app.database_intelligence.synonyms import SYNONYM_MAP
from app.llm.interfaces import ILLMProvider

logger = logging.getLogger(__name__)

INDEX_FORMAT_VERSION = "1.0.0"
CACHE_DIR = os.path.join(os.path.dirname(__file__), "..", "..", ".schema_cache")
INDEX_FILE = os.path.join(CACHE_DIR, "faiss_index.bin")
META_FILE = os.path.join(CACHE_DIR, "metadata.json")


def construct_table_document(table: TableMetadata) -> str:
    """Builds a rich, standardized document representation of a table for semantic indexing.

    Explicitly includes table purpose, column definitions, primary keys, foreign keys/relationships,
    and configured synonyms to improve search recall.
    """
    parts = [
        f"Table Name: {table.name}",
        f"Table Purpose/Description: {table.comment or 'No description comment provided.'}"
    ]

    # Standardize column descriptions and type mappings
    cols = []
    for c in table.columns:
        col_desc = f"{c.name} (type: {c.type_name}"
        if c.primary_key:
            col_desc += ", primary key"
        if c.comment:
            col_desc += f", description: {c.comment}"
        col_desc += ")"
        cols.append(col_desc)
    parts.append(f"Columns and Fields: {'; '.join(cols)}")

    # Standardize primary key info
    if table.primary_keys:
        parts.append(f"Primary Keys: {', '.join(table.primary_keys)}")

    # Standardize relationship and foreign key constraints
    relations = []
    for fk in table.foreign_keys:
        rel_str = (
            f"Table '{table.name}' relates to table '{fk.referred_table}' via the fields "
            f"({', '.join(fk.constrained_columns)}) referencing ({', '.join(fk.referred_columns)})"
        )
        relations.append(rel_str)
    if relations:
        parts.append(f"Relationships and Foreign Keys: {'. '.join(relations)}")

    # Standardize synonyms and semantic tags
    syns = list(SYNONYM_MAP.get(table.name.lower(), []))
    for col in table.columns:
        syns.extend(SYNONYM_MAP.get(col.name.lower(), []))
    if syns:
        parts.append(f"Configured Synonyms and Related Terms: {', '.join(sorted(set(syns)))}")

    return "\n".join(parts)


def get_hash_embedding(text: str, dimension: int = 768) -> list[float]:
    """Generates a deterministic mock embedding vector based on MD5 hashes of words in text."""
    words = text.lower().split()
    if not words:
        return [0.0] * dimension
    vec = np.zeros(dimension, dtype=np.float32)
    for word in words:
        h = int(hashlib.md5(word.encode("utf-8")).hexdigest(), 16)
        np.random.seed(h & 0xFFFFFFFF)
        vec += np.random.randn(dimension).astype(np.float32)

    norm = np.linalg.norm(vec)
    if norm > 0:
        vec = vec / norm
    return vec.tolist()


class SemanticSchemaIndex:
    """Vector search index for table definitions utilizing FAISS and semantic embeddings.

    Supports persistent cache, incremental embedding updates, and validation controls.
    """

    def __init__(
        self,
        schema: DatabaseSchema,
        llm_provider: ILLMProvider | None,
        dimension: int = 768,
    ):
        self.schema = schema
        self.llm_provider = llm_provider
        self.dimension = dimension
        self.index = None
        self.table_names: list[str] = []
        self._cached_metadata: dict = {}
        self.last_embedding_error: dict | None = None

    def _embedding_model_name(self) -> str:
        """Returns the active embedding model identifier used for cache compatibility."""
        if not self.llm_provider:
            return "mock-hash"
        metadata = self.llm_provider.get_metadata()
        if isinstance(metadata, dict):
            for key in ("embedding_model", "model"):
                value = metadata.get(key)
                if isinstance(value, str) and value:
                    return value
        embedding_model = getattr(self.llm_provider, "embedding_model", None)
        if isinstance(embedding_model, str) and embedding_model:
            return embedding_model
        model = getattr(self.llm_provider, "model", None)
        if isinstance(model, str) and model:
            return model
        return "unknown"

    async def _get_embedding(self, text: str) -> list[float]:
        """Generates embedding using LLM provider, falling back to hashed mock embeddings."""
        try:
            if self.llm_provider and hasattr(self.llm_provider, "embed"):
                embedding = await self.llm_provider.embed(text)
                self.last_embedding_error = None
                return embedding
        except Exception as e:
            self.last_embedding_error = {
                "embedding_model": self._embedding_model_name(),
                "exception": str(e),
                "http_status": getattr(e, "http_status", None),
                "response_body": getattr(e, "response_body", None),
                "endpoint": getattr(e, "endpoint", None),
                "duration_ms": getattr(e, "duration_ms", None),
            }
            logger.warning(
                "LLM provider failed to generate embedding. Falling back to hash embedding.",
                extra=self.last_embedding_error,
            )

        return get_hash_embedding(text, self.dimension)

    def load_cache(self) -> bool:
        """Loads index metadata from cache file, validating version and model compatibility."""
        try:
            if not os.path.exists(INDEX_FILE) or not os.path.exists(META_FILE):
                return False

            with open(META_FILE, encoding="utf-8") as f:
                self._cached_metadata = json.load(f)

            # Validate cache compatibility
            cached_version = self._cached_metadata.get("index_format_version")
            if cached_version != INDEX_FORMAT_VERSION:
                logger.info(
                    "Cached index version '%s' mismatch. Expecting '%s'. Rebuilding.",
                    cached_version,
                    INDEX_FORMAT_VERSION,
                )
                return False

            model_name = self._embedding_model_name()
            cached_model = self._cached_metadata.get("embedding_model")
            if cached_model != model_name:
                logger.info(
                    "Cached embedding model '%s' mismatch. Expecting '%s'. Rebuilding.",
                    cached_model,
                    model_name,
                )
                return False

            cached_dim = self._cached_metadata.get("dimension")
            if cached_dim != self.dimension:
                logger.info(
                    "Cached embedding dimension '%s' mismatch. Expecting '%s'. Rebuilding.",
                    cached_dim,
                    self.dimension,
                )
                return False

            return True
        except Exception as e:
            logger.warning(f"Failed to load FAISS cache: {e}")
            return False

    def save_cache(self, fingerprints: dict[str, str], embeddings: dict[str, list[float]]) -> None:
        """Saves current index structure and computed embeddings metadata to cache files."""
        try:
            os.makedirs(CACHE_DIR, exist_ok=True)
            faiss.write_index(self.index, INDEX_FILE)

            model_name = self._embedding_model_name()
            metadata = {
                "index_format_version": INDEX_FORMAT_VERSION,
                "embedding_model": model_name,
                "dimension": self.dimension,
                "schema_fingerprint": self.schema.fingerprint,
                "table_names": self.table_names,
                "table_fingerprints": fingerprints,
                "table_embeddings": embeddings,
            }
            with open(META_FILE, "w", encoding="utf-8") as f:
                json.dump(metadata, f, indent=2)
            logger.info(f"Persisted FAISS index and metadata cache to {CACHE_DIR}")
        except Exception as e:
            logger.warning(f"Failed to save FAISS cache: {e}")

    async def build_index(self) -> None:
        """Constructs and populates the FAISS index with incremental updates support."""
        # 1. Try to load cache metadata
        cache_loaded = self.load_cache()

        # Check if entire schema matches cached version
        if (
            cache_loaded
            and self._cached_metadata.get("schema_fingerprint") == self.schema.fingerprint
        ):
            try:
                self.table_names = self._cached_metadata.get("table_names", [])
                self.index = faiss.read_index(INDEX_FILE)
                logger.info("Database schema unchanged. Reusing cached FAISS index successfully.")
                return
            except Exception as e:
                logger.warning(f"Failed to read index file: {e}. Recomputing.")

        # 2. Build or reload incrementally
        cached_fingerprints = (
            self._cached_metadata.get("table_fingerprints", {}) if cache_loaded else {}
        )
        cached_embeddings = (
            self._cached_metadata.get("table_embeddings", {}) if cache_loaded else {}
        )

        active_fingerprints: dict[str, str] = {}
        active_embeddings: dict[str, list[float]] = {}
        self.table_names = []

        reused_count = 0
        computed_count = 0

        # Process each table in schema
        for table_name, table in self.schema.tables.items():
            doc = construct_table_document(table)
            doc_hash = hashlib.sha256(doc.encode("utf-8")).hexdigest()
            active_fingerprints[table_name] = doc_hash
            self.table_names.append(table_name)

            # Incremental check: reuse if document hash is identical
            if (
                table_name in cached_fingerprints
                and cached_fingerprints[table_name] == doc_hash
                and table_name in cached_embeddings
            ):
                active_embeddings[table_name] = cached_embeddings[table_name]
                reused_count += 1
            else:
                # Generate new embedding
                emb = await self._get_embedding(doc)
                active_embeddings[table_name] = emb
                computed_count += 1

        if not self.table_names:
            logger.warning("No table documents found to index.")
            return

        # Fetch list ordered by table_names
        embeddings_list = [active_embeddings[name] for name in self.table_names]

        # Convert to numpy array of float32
        data = np.array(embeddings_list, dtype=np.float32)
        self.dimension = data.shape[1]

        # Normalize vectors for Cosine Similarity (IndexFlatIP)
        norms = np.linalg.norm(data, axis=1, keepdims=True)
        norms[norms == 0] = 1.0
        data = data / norms

        self.index = faiss.IndexFlatIP(self.dimension)
        self.index.add(data)

        logger.info(
            f"Successfully built FAISS semantic index (dim={self.dimension}). "
            f"Reused {reused_count} embeddings, computed {computed_count} new embeddings."
        )

        # 3. Persist compiled index and mappings to disk
        self.save_cache(active_fingerprints, active_embeddings)

    async def search(self, query: str, k: int = 5) -> list[tuple[str, float]]:
        """Searches index for matching table names, returning name and cosine similarity score."""
        if self.index is None or not self.table_names:
            logger.warning("FAISS index is not built or empty.")
            return []

        query_emb = await self._get_embedding(query)
        query_vector = np.array([query_emb], dtype=np.float32)

        # Normalize query vector
        norm = np.linalg.norm(query_vector)
        if norm > 0:
            query_vector = query_vector / norm

        # Search index
        limit = min(k, len(self.table_names))
        distances, indices = self.index.search(query_vector, limit)

        results = []
        for dist, idx in zip(distances[0], indices[0], strict=False):
            if idx >= 0 and idx < len(self.table_names):
                results.append((self.table_names[idx], float(dist)))

        # Sort by distance descending
        results.sort(key=lambda x: x[1], reverse=True)
        return results
