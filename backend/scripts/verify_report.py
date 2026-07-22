import asyncio
import json
import logging
import re
import sys
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import AsyncMock

# Add backend directory to sys.path to resolve 'app' correctly
backend_dir = Path(__file__).resolve().parent.parent
if str(backend_dir) not in sys.path:
    sys.path.insert(0, str(backend_dir))

import sys
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

from app.bootstrap import container
from app.agent import AgentState, AgentGraphBuilder
from app.application_models.generated_report import GeneratedReport
from app.application_models.generated_sql import GeneratedSQL
from app.application_models.workflow_models import QueryResult
from app.llm.interfaces import ILLMProvider
from app.llm.schemas import LLMResponse
from app.services.report_generator import IReportGenerator
from app.services.report_service import ReportService
from app.services.workflow_service import WorkflowService
from app.sql_validator.models import SQLValidationResult


class DynamicMockReportGenerator(IReportGenerator):
    """Mock report strategy that dynamically extracts QueryResult data from the prompt."""

    async def generate(self, prompt: str, llm_provider: ILLMProvider) -> LLMResponse:
        rows = []
        original_row_count = 0
        question = "Database Query Report"

        # Regex match the JSON serialized context in the prompt
        json_match = re.search(r"\{.*\}", prompt, re.DOTALL)
        if json_match:
            try:
                data = json.loads(json_match.group(0))
                rows = data.get("rows", [])
                original_row_count = data.get("original_row_count", 0)
                question = data.get("question", question)
            except Exception:
                pass

        # Extract doctor name and appointments count from actual query rows
        doctor_name = "Bilinmeyen Doktor"
        appointments = 0
        if rows:
            row = rows[0]
            doctor_name = row.get("ad_soyad", row.get("name", "Bilinmeyen Doktor"))
            appointments = row.get("randevu_sayisi", row.get("id", 0))

        markdown = f"""# {question} Raporu

## Executive Summary
Bu rapor, "{question}" sorusuna yanıt olarak oluşturulmuştur. Yapılan analiz sonucunda en çok randevusu olan doktor belirlenmiştir.

## Key Findings
En yüksek randevu sayısına sahip doktor bilgisi aşağıdadır:
| Doktor Adı | Randevu Sayısı |
| :--- | :--- |
| {doctor_name} | {appointments} |

## Recommendations
Randevu yoğunluğu {appointments} olan Dr. {doctor_name} için asistan desteği sağlanması önerilmektedir.

## Data Notes
Orijinal veri kümesinde toplam {original_row_count} kayıt bulunmaktadır.
"""
        return LLMResponse(
            content=markdown,
            model="mock-qwen3:8b",
            latency_ms=150.0,
            prompt_tokens=300,
            completion_tokens=150,
        )


async def run_with_mock_llm():
    print("\n--- Running Verification with Mock LLM ---")

    # The actual T-SQL query to validate and run on dbo.vw_RandevuRaporu
    target_sql = """
    SELECT TOP (1) GenelRandevuBolumAdi, COUNT(Id) AS randevu_sayisi
    FROM dbo.vw_RandevuRaporu
    GROUP BY GenelRandevuBolumAdi
    ORDER BY randevu_sayisi DESC;
    """

    # 1. Setup mock SQL generation to return our valid read-only query
    sql_service_mock = AsyncMock(spec=container.sql_service)
    sql_service_mock.generate_sql.return_value = GeneratedSQL(
        sql=target_sql,
        normalized_sql=target_sql.strip(),
        validation_result=SQLValidationResult(
            valid=True,
            normalized_sql=target_sql.strip(),
            statement_type="Select"
        ),
        provider="mock-ollama",
        model="qwen3:8b",
        latency_ms=120.0
    )

    # 2. Build real ReportService using the dynamic mock generator strategy
    dynamic_report_generator = DynamicMockReportGenerator()
    report_service_mock = ReportService(
        prompt_service=container.prompt_service,
        llm_provider=container.llm_provider,
        generator=dynamic_report_generator
    )

    # 3. Create real WorkflowService orchestrator mapping SQL mock and dynamic report service
    real_workflow_service = WorkflowService(
        prompt_service=container.prompt_service,
        sql_service=sql_service_mock,
        report_service=report_service_mock,
        execution_service=container.execution_service
    )

    # 4. Build E2E graph with the mocked workflow components
    builder = AgentGraphBuilder(
        prompt_service=container.prompt_service,
        workflow_service=real_workflow_service
    )
    graph = builder.build()

    # 5. Trigger E2E graph invoke
    state = AgentState(
        question="Which doctor has the highest number of appointments?",
        workflow_id="wf-mock-verify",
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

        query_result = final_state.get("query_result")
        if query_result:
            print("\n===== REAL DATABASE RESULT ROWS =====")
            for idx, row in enumerate(query_result.rows):
                print(f"  Row {idx + 1}: {row}")

        report = final_state.get("generated_report")
        if report:
            print("\n===== GENERATED NARRATIVE REPORT =====")
            print(report.markdown)

            print("\n===== REPORT METADATA =====")
            print(f"  Title              : {report.title}")
            print(f"  Provider           : {report.provider}")
            print(f"  Model              : {report.model}")
            print(f"  Latency            : {report.latency_ms:.2f} ms")
            print(f"  Prompt Tokens      : {report.prompt_tokens}")
            print(f"  Completion Tokens  : {report.completion_tokens}")
            print(f"  Generated At       : {report.generated_at}")
            print(f"  Execution ID       : {report.execution_id}")
        else:
            print("\n[WARNING] No GeneratedReport exists on final state.")

    except Exception as e:
        print(f"\n[FATAL ERROR] Mocked workflow execution failed: {e}")


async def main():
    print("=== AI Agent Report Generation Layer Manual Verification ===")
    
    question = "Which doctor has the highest number of appointments?"
    print(f"\nUser Question: {question}")
    
    # Run the mocked LLM run to verify validation & execution & report nodes path
    await run_with_mock_llm()


if __name__ == "__main__":
    # Suppress verbose startup logging to print clean execution stats
    logging.basicConfig(level=logging.WARNING)
    logging.getLogger("app.bootstrap").setLevel(logging.WARNING)
    logging.getLogger("app.agent").setLevel(logging.WARNING)
    asyncio.run(main())


