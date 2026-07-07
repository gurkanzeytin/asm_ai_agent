import logging
from typing import Optional

from app.application_models.generated_report import GeneratedReport
from app.application_models.generated_sql import GeneratedSQL
from app.application_models.workflow_models import QueryResult
from app.services.exceptions import WorkflowServiceException
from app.services.interfaces import (
    IExecutionService,
    IPromptService,
    IReportService,
    ISQLService,
    IWorkflowService,
)

logger = logging.getLogger(__name__)


class WorkflowService(IWorkflowService):
    """Pure orchestrator class coordinating prompt, sql, report, and execution services."""

    def __init__(
        self,
        prompt_service: IPromptService,
        sql_service: ISQLService,
        report_service: IReportService,
        execution_service: Optional[IExecutionService] = None,
    ):
        self.prompt_service = prompt_service
        self.sql_service = sql_service
        self.report_service = report_service
        self.execution_service = execution_service

    async def execute_sql_generation(self, question: str) -> GeneratedSQL:
        """Coordinates prompt compilation and SQL validation delegation."""
        logger.info("WorkflowService execute_sql_generation started.")
        try:
            prompt = await self.prompt_service.render_sql_prompt(question)
            sql_dto = await self.sql_service.generate_sql(prompt)
            logger.info("WorkflowService execute_sql_generation completed successfully.")
            return sql_dto
        except Exception as e:
            logger.error(f"WorkflowService execute_sql_generation failed: {e}")
            raise WorkflowServiceException(f"Workflow execution failed: {e}") from e

    async def execute_report_generation(
        self, question: str, sql: str, query_result: QueryResult, execution_id: Optional[str] = None
    ) -> GeneratedReport:
        """Coordinates narrative report generation delegation."""
        logger.info("WorkflowService execute_report_generation started.")
        try:
            report_dto = await self.report_service.generate_report(
                question, sql, query_result, execution_id
            )
            logger.info("WorkflowService execute_report_generation completed successfully.")
            return report_dto
        except Exception as e:
            logger.error(f"WorkflowService execute_report_generation failed: {e}")
            raise WorkflowServiceException(f"Workflow execution failed: {e}") from e

    async def execute_query(self, sql: str) -> QueryResult:
        """Orchestrates query execution and maps result set DTO."""
        logger.info("WorkflowService execute_query started.")
        if not self.execution_service:
            logger.error("WorkflowService execute_query failed: execution_service is not configured.")
            raise WorkflowServiceException("Execution service is not configured on WorkflowService.")
        try:
            query_result = await self.execution_service.execute_sql(sql)
            logger.info("WorkflowService execute_query completed successfully.")
            return query_result
        except Exception as e:
            logger.error(f"WorkflowService execute_query failed: {e}")
            raise WorkflowServiceException(f"Workflow query execution failed: {e}") from e
