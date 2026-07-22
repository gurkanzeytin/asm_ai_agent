import asyncio
import logging
import sys
from pathlib import Path
from unittest.mock import AsyncMock

# Add backend directory to sys.path to resolve 'app' correctly
backend_dir = Path(__file__).resolve().parent.parent
if str(backend_dir) not in sys.path:
    sys.path.insert(0, str(backend_dir))

from app.bootstrap import container
from app.agent import AgentState, AgentGraphBuilder
from app.application_models.generated_sql import GeneratedSQL
from app.sql_validator.models import SQLValidationResult


async def run_with_mock_llm():
    print("\n--- Running Successful Workflow Case (Mock LLM -> Real Database) ---")
    
    # 1. Setup mock workflow service to simulate successful LLM SQL generation
    # but still use the real prompt and execution services in the graph
    workflow_service_mock = AsyncMock(spec=container.workflow_service)
    
    # The actual T-SQL query to validate and run on dbo.vw_RandevuRaporu
    target_sql = """
    SELECT TOP (1) GenelRandevuBolumAdi, COUNT(Id) AS randevu_sayisi
    FROM dbo.vw_RandevuRaporu
    GROUP BY GenelRandevuBolumAdi
    ORDER BY randevu_sayisi DESC;
    """

    # Mock SQL generation to return our valid read-only query
    workflow_service_mock.execute_sql_generation.return_value = GeneratedSQL(
        sql=target_sql,
        normalized_sql=target_sql.strip(),
        validation_result=SQLValidationResult(
            valid=True,
            normalized_sql=target_sql.strip(),
            statement_type="Select"
        ),
        provider="ollama",
        model="qwen3:8b",
        latency_ms=120.0
    )

    # Delegate execute_query to the actual production execution service
    async def delegate_execute_query(sql_str):
        return await container.workflow_service.execute_query(sql_str)
    workflow_service_mock.execute_query.side_effect = delegate_execute_query

    # 2. Build temporary graph with the mocked workflow service
    builder = AgentGraphBuilder(
        prompt_service=container.prompt_service,
        workflow_service=workflow_service_mock
    )
    graph = builder.build()

    # 3. Trigger E2E graph invoke
    state = AgentState(
        question="Which doctor has the highest number of appointments?",
        workflow_id="wf-e2e-success-val",
    )

    try:
        final_state = await graph.ainvoke(state)

        print("\n===== PIPELINE LIFECYCLE SUMMARY =====")
        print(f"Current Node     : {final_state.get('current_node')}")
        print(f"Completed Nodes  : {final_state.get('completed_nodes')}")
        print(f"Errors Logged    : {final_state.get('errors')}")
        print(f"Pipeline Duration: {final_state.get('duration_ms'):.2f} ms")

        gen_sql = final_state.get("generated_sql")
        print("\n===== GENERATED SQL STATEMENT =====")
        print(gen_sql.sql.strip())
        print(f"  Safety Validated : {gen_sql.validation_result.valid}")

        query_result = final_state.get("query_result")
        if query_result:
            print("\n===== SQL QUERY EXECUTION METADATA =====")
            print(f"  Success           : {query_result.success}")
            print(f"  Total Row Count   : {query_result.row_count}")
            print(f"  Execution Timing  : {query_result.execution_time_ms:.2f} ms")
            print(f"  Database Provider : {query_result.database_provider}")

            print("\n===== REAL DATABASE RESULT ROWS =====")
            for idx, row in enumerate(query_result.rows):
                print(f"  Row {idx + 1}: {row}")
        else:
            print("\n[WARNING] No QueryResult metadata exists on final state.")

    except Exception as e:
        print(f"\n[FATAL ERROR] Mocked workflow execution failed: {e}")


async def main():
    print("=== AI Agent SQL Execution Layer Manual Verification ===")
    
    question = "Which doctor has the highest number of appointments?"
    print(f"\nUser Question: {question}")
    print("Starting actual agent workflow pipeline execution (expects local Ollama)...")

    # Fetch compiled agent_graph from container composition root
    graph = container.agent_graph

    initial_state = AgentState(
        question=question,
        workflow_id="wf-e2e-exec-val",
    )

    try:
        final_state = await graph.ainvoke(initial_state)

        print("\n===== PIPELINE LIFECYCLE SUMMARY =====")
        print(f"Current Node     : {final_state.get('current_node')}")
        print(f"Completed Nodes  : {final_state.get('completed_nodes')}")
        print(f"Errors Logged    : {final_state.get('errors')}")
        print(f"Pipeline Duration: {final_state.get('duration_ms'):.2f} ms")

        gen_sql = final_state.get("generated_sql")
        if gen_sql:
            print("\n===== GENERATED SQL STATEMENT =====")
            print(gen_sql.sql)
            
            val_res = gen_sql.validation_result
            if val_res:
                print(f"  Safety Validated : {val_res.valid}")
                print(f"  Statement Type   : {val_res.statement_type}")
        else:
            print("\n[WARNING] No generated SQL was produced by the agent.")

        query_result = final_state.get("query_result")
        if query_result:
            print("\n===== SQL QUERY EXECUTION METADATA =====")
            print(f"  Success           : {query_result.success}")
            print(f"  Total Row Count   : {query_result.row_count}")
            print(f"  Database Provider : {query_result.database_provider}")
        else:
            print("\n[WARNING] No QueryResult metadata exists on final state.")

    except Exception as e:
        print(f"\n[FATAL ERROR] Workflow execution encountered exception: {e}")

    # Now run the mocked LLM run to verify validation & execution nodes path
    await run_with_mock_llm()


if __name__ == "__main__":
    # Suppress verbose startup logging to print clean execution stats
    logging.basicConfig(level=logging.WARNING)
    logging.getLogger("app.bootstrap").setLevel(logging.WARNING)
    logging.getLogger("app.agent").setLevel(logging.WARNING)
    asyncio.run(main())
