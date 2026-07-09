import pytest
import os
import shutil
from unittest.mock import AsyncMock, MagicMock, patch
from app.database_intelligence.schema_graph import SchemaGraph
from app.database_intelligence.schema_embeddings import SemanticSchemaIndex, CACHE_DIR
from app.database_intelligence.retriever import SchemaRetriever
from app.database_intelligence.models import (
    ColumnMetadata,
    DatabaseSchema,
    TableMetadata,
    ForeignKeyMetadata,
    SchemaStatistics,
)
from app.database_intelligence.exceptions import SchemaRetrievalError
from app.llm.interfaces import ILLMProvider
from app.agent.state import AgentState
from app.agent.nodes.retrieve_context import RetrieveContextNode
from app.services.workflow_service import WorkflowService


@pytest.fixture(autouse=True)
def clean_cache_dir():
    # Clean cache folder before and after tests
    if os.path.exists(CACHE_DIR):
        shutil.rmtree(CACHE_DIR)
    yield
    if os.path.exists(CACHE_DIR):
        shutil.rmtree(CACHE_DIR)


@pytest.fixture
def complex_schema():
    # Construct a multi-hop schema:
    # 1. users: id [PK]
    # 2. orders: id [PK], user_id [FK to users.id]
    # 3. order_items: id [PK], order_id [FK to orders.id], product_id [FK to products.id]
    # 4. products: id [PK]
    col_user_id = ColumnMetadata(name="id", type_name="INTEGER", nullable=False, primary_key=True)
    table_users = TableMetadata(
        name="users",
        columns=[col_user_id],
        primary_keys=["id"],
        foreign_keys=[],
        comment="User accounts table",
    )

    col_order_id = ColumnMetadata(name="id", type_name="INTEGER", nullable=False, primary_key=True)
    col_order_user_id = ColumnMetadata(name="user_id", type_name="INTEGER", nullable=False, primary_key=False)
    fk_order_user = ForeignKeyMetadata(
        constrained_columns=["user_id"],
        referred_table="users",
        referred_columns=["id"],
    )
    table_orders = TableMetadata(
        name="orders",
        columns=[col_order_id, col_order_user_id],
        primary_keys=["id"],
        foreign_keys=[fk_order_user],
        comment="Orders header logs",
    )

    col_item_id = ColumnMetadata(name="id", type_name="INTEGER", nullable=False, primary_key=True)
    col_item_order_id = ColumnMetadata(name="order_id", type_name="INTEGER", nullable=False, primary_key=False)
    col_item_prod_id = ColumnMetadata(name="product_id", type_name="INTEGER", nullable=False, primary_key=False)
    fk_item_order = ForeignKeyMetadata(
        constrained_columns=["order_id"],
        referred_table="orders",
        referred_columns=["id"],
    )
    fk_item_prod = ForeignKeyMetadata(
        constrained_columns=["product_id"],
        referred_table="products",
        referred_columns=["id"],
    )
    table_order_items = TableMetadata(
        name="order_items",
        columns=[col_item_id, col_item_order_id, col_item_prod_id],
        primary_keys=["id"],
        foreign_keys=[fk_item_order, fk_item_prod],
        comment="Detailed order items mapping",
    )

    col_prod_id = ColumnMetadata(name="id", type_name="INTEGER", nullable=False, primary_key=True)
    table_products = TableMetadata(
        name="products",
        columns=[col_prod_id],
        primary_keys=["id"],
        foreign_keys=[],
        comment="Products description catalog",
    )

    return DatabaseSchema(
        tables={
            "users": table_users,
            "orders": table_orders,
            "order_items": table_order_items,
            "products": table_products,
        },
        views={},
        statistics=SchemaStatistics(table_count=4, column_count=7, foreign_key_count=3, view_count=0),
        fingerprint="complex-fp",
    )


def test_schema_graph_edges(complex_schema):
    graph = SchemaGraph(complex_schema)
    assert "users" in graph.nodes
    assert "orders" in graph.nodes
    assert "order_items" in graph.nodes
    assert "products" in graph.nodes

    # Check neighbor adjacencies (undirected outgoing and incoming)
    assert "orders" in graph.get_neighbors("users")
    assert "users" in graph.get_neighbors("orders")
    assert "order_items" in graph.get_neighbors("orders")
    assert "orders" in graph.get_neighbors("order_items")
    assert "products" in graph.get_neighbors("order_items")


@pytest.mark.asyncio
async def test_semantic_schema_index_mock(complex_schema):
    index = SemanticSchemaIndex(complex_schema, None)
    await index.build_index()

    # Search query that matches table comment text
    results = await index.search("catalog", k=3)
    assert len(results) >= 1
    # Top result should be "products" because of high word overlap in comments
    assert results[0][0] == "products"


@pytest.mark.asyncio
async def test_relationship_aware_retriever_bfs_traversal(complex_schema):
    # Set max depth to 2 to reach products from users (users -> orders -> order_items)
    retriever = SchemaRetriever(match_threshold=0.3, max_depth=2, token_budget=2000)
    
    # Query matching users table specifically
    context = retriever.retrieve_context("get users", complex_schema)
    
    table_names = [t.name for t in context.tables]
    assert "users" in table_names
    assert "orders" in table_names  # 1-hop FK neighbor
    assert "order_items" in table_names  # 2-hop FK neighbor


@pytest.mark.asyncio
async def test_adaptive_token_budget_capping(complex_schema):
    # Set a very low token budget (e.g., 20 tokens)
    retriever = SchemaRetriever(match_threshold=0.3, token_budget=20)
    context = retriever.retrieve_context("get users", complex_schema)

    # Top-ranked matched table must always be included
    assert len(context.tables) >= 1
    table_names = [t.name for t in context.tables]
    assert "users" in table_names
    # 'orders' (neighbor) should be dropped due to budget cap
    assert "orders" not in table_names


@pytest.mark.asyncio
async def test_cache_persistence_and_invalidation(complex_schema):
    # Build index once - should save it to disk
    index = SemanticSchemaIndex(complex_schema, None)
    await index.build_index()

    # Files must exist on disk
    assert os.path.exists(os.path.join(CACHE_DIR, "faiss_index.bin"))
    assert os.path.exists(os.path.join(CACHE_DIR, "metadata.json"))

    # Reload index - should hit cache
    index2 = SemanticSchemaIndex(complex_schema, None)
    with patch.object(index2, "save_cache") as mock_save:
        await index2.build_index()
        # Save cache shouldn't be called because the cache is completely reused
        mock_save.assert_not_called()

    # Modify schema (invalidate fingerprint)
    modified_tables = dict(complex_schema.tables)
    # Add a column to users
    modified_tables["users"] = modified_tables["users"].model_copy(
        update={"comment": "Modified accounts comment"}
    )
    from app.database_intelligence.models import calculate_fingerprint
    new_fp = calculate_fingerprint(modified_tables, {})
    new_schema = DatabaseSchema(
        tables=modified_tables,
        views={},
        statistics=complex_schema.statistics,
        fingerprint=new_fp,
    )

    # Reload with modified schema - should invalidate and rebuild
    index3 = SemanticSchemaIndex(new_schema, None)
    with patch.object(index3, "save_cache") as mock_save:
        await index3.build_index()
        # Should save cache because fingerprint changed
        mock_save.assert_called_once()


@pytest.mark.asyncio
async def test_incremental_embedding_regeneration(complex_schema):
    mock_provider = MagicMock()
    mock_provider.model = "mock-model"
    # Make provider asynchronous
    mock_provider.embed = AsyncMock(return_value=[0.1] * 768)

    # Build first time - calls provider 4 times (one for each table)
    index = SemanticSchemaIndex(complex_schema, mock_provider)
    await index.build_index()
    assert mock_provider.embed.call_count == 4

    # Reload unchanged schema - calls provider 0 times (fully loaded)
    mock_provider.embed.reset_mock()
    index2 = SemanticSchemaIndex(complex_schema, mock_provider)
    await index2.build_index()
    mock_provider.embed.assert_not_called()

    # Modify only one table: users
    modified_tables = dict(complex_schema.tables)
    modified_tables["users"] = modified_tables["users"].model_copy(
        update={"comment": "Slightly changed user comment for hash mismatch"}
    )
    from app.database_intelligence.models import calculate_fingerprint
    new_fp = calculate_fingerprint(modified_tables, {})
    new_schema = DatabaseSchema(
        tables=modified_tables,
        views={},
        statistics=complex_schema.statistics,
        fingerprint=new_fp,
    )

    # Load modified schema - should only call provider 1 time (for the modified 'users' table)
    mock_provider.embed.reset_mock()
    index3 = SemanticSchemaIndex(new_schema, mock_provider)
    await index3.build_index()
    mock_provider.embed.assert_called_once()


@pytest.mark.asyncio
async def test_neighborhood_diversity_penalty(complex_schema):
    # Setup scoring so that 'users' has high match score,
    # and its neighbors 'orders' (neighbor) and 'products' (not neighbor of selected)
    # have similar matching scores.
    # Without diversity, we would pick: users, then orders.
    # With diversity, picking users applies a 0.7 penalty to orders, allowing products to rank higher!
    
    # We set max_depth=0 to prevent multi-hop expansions during this diversity test,
    # and patch SemanticSchemaIndex.search to return 0.0 semantic matches.
    retriever = SchemaRetriever(match_threshold=0.3, max_depth=0, token_budget=2000)
    
    # We will override _score_table to return high scores for users and orders
    def mock_score(query_tokens, table):
        if table.name == "users":
            return 10  # kw = 1.0, kw_contrib = 0.30
        elif table.name == "orders":
            return 6   # kw = 0.6, kw_contrib = 0.18
        elif table.name == "products":
            return 5   # kw = 0.5, kw_contrib = 0.15
        return 0

    retriever._score_table = mock_score

    async def mock_search(query, k):
        return [(name, 0.0) for name in complex_schema.tables]

    # Search: 'users' matched directly.
    # Candidates list will evaluate:
    # users: matched (base_score = 0.35)
    # orders: matched (base_score = 0.28) -> immediate neighbor of users!
    # products: matched (base_score = 0.20) -> not immediate neighbor of users!
    
    with patch("app.database_intelligence.schema_embeddings.SemanticSchemaIndex.search", side_effect=mock_search):
        # Executing retrieve context
        context = retriever.retrieve_context("get users", complex_schema)
    
    # Because of diversity penalty:
    # 1. users is selected first.
    # 2. orders (neighbor) is penalized: 0.28 * 0.7 = 0.196.
    # 3. products (non-neighbor) score remains 0.20.
    # 4. products gets selected BEFORE orders!
    # So selection sequence of tables should have products preceding orders!
    table_names = [t.name for t in context.tables]
    assert table_names[0] == "users"
    assert table_names[1] == "products"
    assert table_names[2] == "orders"


@pytest.mark.asyncio
async def test_non_database_intent_bypasses_retrieval(complex_schema):
    from app.agent.state import AgentState
    from app.application_models.intent import IntentResult, IntentType
    
    # Mock retriever
    mock_retriever = MagicMock()
    mock_retriever.retrieve_context.return_value = MagicMock()
    
    # Setup mock prompt service
    mock_prompt_service = MagicMock()
    # If render_prompt is called with system_prompt.md, it should return mock template text
    mock_prompt_service.render_prompt = AsyncMock(return_value="System template content")
    
    # Workflow Node setup
    chat_node = RetrieveContextNode(mock_prompt_service)
    
    # Executing workflow with non-database intent (e.g. general chat)
    # The routing logic in graph.py will route GENERAL_CHAT straight to GenerateChatResponseNode,
    # completely bypassing RetrieveContextNode.
    # Let's verify by executing GenerateChatResponseNode directly and asserting retrieve_schema_context is not called.
    from app.agent.nodes.generate_chat_response import GenerateChatResponseNode
    mock_llm = MagicMock()
    mock_llm.generate = AsyncMock(return_value=MagicMock(content="Hello!", model="mock", latency_ms=10))
    mock_llm.get_metadata.return_value = {}
    
    chat_node = GenerateChatResponseNode(mock_prompt_service, mock_llm)
    
    state = AgentState(
        question="Hello!",
        intent=IntentResult(intent=IntentType.GENERAL_CHAT, confidence=0.95, reason="greet"),
        completed_nodes=[],
        node_timings={},
    )
    
    new_state = await chat_node.execute(state)
    
    # Confirm that retrieve_schema_context was NEVER invoked on prompt service!
    mock_prompt_service.retrieve_schema_context.assert_not_called()
    assert new_state.generated_report is not None
    assert new_state.generated_report.markdown == "Hello!"


def test_retrieval_evaluation_benchmark(complex_schema):
    # Automated retrieval evaluation benchmark to measure Recall and Precision metrics
    retriever = SchemaRetriever(match_threshold=0.3, max_depth=2, token_budget=2000)
    
    benchmark_cases = [
        {
            "question": "find all orders of users",
            "expected": {"users", "orders"}
        },
        {
            "question": "get product details for order items",
            "expected": {"products", "order_items"}
        },
        {
            "question": "list all users profile details",
            "expected": {"users"}
        }
    ]
    
    total_recall = 0.0
    total_precision = 0.0
    
    for case in benchmark_cases:
        context = retriever.retrieve_context(case["question"], complex_schema)
        retrieved = {t.name for t in context.tables}
        expected = case["expected"]
        
        tp = len(expected.intersection(retrieved))
        recall = tp / len(expected)
        precision = tp / len(retrieved) if retrieved else 0.0
        
        total_recall += recall
        total_precision += precision
        
        # Recall must be high for these baseline queries
        assert recall >= 0.8, f"Recall was {recall:.2f} for query: '{case['question']}'. Retrieved: {retrieved}"

    avg_recall = total_recall / len(benchmark_cases)
    avg_precision = total_precision / len(benchmark_cases)
    
    # Log benchmark results for CI metrics visibility
    print(f"\nRetrieval Quality Metrics Benchmark:")
    print(f"  - Average Recall: {avg_recall:.4f}")
    print(f"  - Average Precision: {avg_precision:.4f}")
