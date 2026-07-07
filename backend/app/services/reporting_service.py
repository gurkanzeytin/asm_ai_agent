import logging
import uuid
from typing import Any

from app.agent.state import AgentState
from app.application_models.workflow_result import WorkflowResult

logger = logging.getLogger(__name__)


class ReportingService:
    """Orchestrates the complete AI reporting workflow by invoking the compiled agent graph.

    Acts as the sole entry point for the API layer. All internal DTOs are mapped into
    a typed WorkflowResult before returning; no internal model is leaked to the transport layer.
    """

    def __init__(self, agent_graph: Any) -> None:
        """Initializes the service with the pre-compiled LangGraph state machine.

        Args:
            agent_graph: Compiled LangGraph CompiledStateGraph instance.
        """
        self._agent_graph = agent_graph

    async def run_workflow(self, question: str) -> WorkflowResult:
        """Runs the full agent graph pipeline and returns a typed WorkflowResult.

        Args:
            question: Natural-language question submitted by the user.

        Returns:
            WorkflowResult: Typed DTO containing all workflow outputs.

        Raises:
            Domain exceptions from the service layer are intentionally propagated
            so that the global exception handlers can map them to HTTP responses.
        """
        workflow_id = str(uuid.uuid4())
        logger.info(f"ReportingService: Starting workflow run [{workflow_id}] for question: {question!r}")

        initial_state = AgentState(question=question, workflow_id=workflow_id)

        # Run compiled LangGraph workflow pipeline — domain exceptions propagate upward
        final_state = await self._agent_graph.ainvoke(initial_state)

        generated_sql_dto = final_state.get("generated_sql")
        query_result_dto = final_state.get("query_result")
        generated_report_dto = final_state.get("generated_report")
        errors = final_state.get("errors", [])

        logger.info(
            f"ReportingService: Workflow [{workflow_id}] completed. "
            f"Errors: {errors or 'none'}"
        )

        return WorkflowResult(
            workflow_id=workflow_id,
            question=question,
            generated_sql=generated_sql_dto.sql if generated_sql_dto else None,
            query_result=query_result_dto,
            generated_report=generated_report_dto,
            errors=errors,
        )
