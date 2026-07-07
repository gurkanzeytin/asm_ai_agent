import logging
import time

import sqlglot
import sqlglot.expressions as exp
from sqlglot.errors import ParseError

from app.core.config import settings
from app.sql_validator.exceptions import SQLParsingException, UnsafeSQLException
from app.sql_validator.interfaces import ISQLValidator
from app.sql_validator.models import SQLValidationResult
from app.sql_validator.rules import ALLOWED_ROOT_NODES, FORBIDDEN_AST_NODES

logger = logging.getLogger(__name__)


class SQLValidator(ISQLValidator):
    """AST-based SQL validator validating query safety and read-only status using sqlglot."""

    def __init__(self, dialect: str | None = None):
        self.dialect = dialect or getattr(settings, "SQL_DIALECT", "sqlite")

    def validate(self, sql: str) -> SQLValidationResult:
        """Parses, inspects, and normalizes the SQL query to ensure read-only safety."""
        start_time = time.perf_counter()
        logger.info("SQL safety validation started.")

        cleaned_sql = sql.strip()
        if not cleaned_sql:
            duration = (time.perf_counter() - start_time) * 1000
            logger.warning("Empty SQL query provided.")
            return SQLValidationResult(
                valid=False,
                reason="Query is empty.",
                warnings=["Empty input query"],
            )

        try:
            # Parse all statements using sqlglot
            expressions = sqlglot.parse(cleaned_sql, read=self.dialect)
        except ParseError as e:
            duration = (time.perf_counter() - start_time) * 1000
            logger.error("SQL syntax parsing failed.", extra={"duration_ms": duration})
            return SQLValidationResult(
                valid=False,
                reason=f"SQL syntax parsing failed: {e}",
                warnings=[f"Syntax error: {e}"],
            )
        except Exception as e:
            duration = (time.perf_counter() - start_time) * 1000
            logger.error(f"Unexpected parser failure: {e}", extra={"duration_ms": duration})
            return SQLValidationResult(
                valid=False,
                reason=f"Parser failed with unexpected error: {e}",
                warnings=["Unexpected parser failure"],
            )

        if not expressions or expressions[0] is None:
            duration = (time.perf_counter() - start_time) * 1000
            logger.error("No valid SQL statements parsed.", extra={"duration_ms": duration})
            return SQLValidationResult(
                valid=False,
                reason="Query does not contain any valid SQL statement.",
            )

        if len(expressions) > 1:
            duration = (time.perf_counter() - start_time) * 1000
            logger.error(
                f"Multiple SQL statements detected ({len(expressions)} statements).",
                extra={"duration_ms": duration},
            )
            return SQLValidationResult(
                valid=False,
                reason="Multiple SQL statements are rejected for safety.",
            )

        expression = expressions[0]
        statement_type = expression.__class__.__name__

        # Resolve root level node if CTE wrapper WITH is present
        root_expr = expression
        if isinstance(expression, exp.With):
            root_expr = expression.this

        if not isinstance(root_expr, ALLOWED_ROOT_NODES):
            duration = (time.perf_counter() - start_time) * 1000
            logger.error(
                f"Unsafe root SQL statement type detected: {statement_type}.",
                extra={"duration_ms": duration},
            )
            return SQLValidationResult(
                valid=False,
                statement_type=statement_type,
                reason=f"Unsafe root statement type '{statement_type}'. Only SELECT statements are permitted.",
            )

        # Traverse AST check for any mutating nodes
        for node in expression.walk():
            if isinstance(node, FORBIDDEN_AST_NODES):
                node_type = node.__class__.__name__
                duration = (time.perf_counter() - start_time) * 1000
                logger.error(
                    f"Forbidden mutating node detected in SQL query AST: {node_type}.",
                    extra={"duration_ms": duration},
                )
                return SQLValidationResult(
                    valid=False,
                    statement_type=statement_type,
                    reason=f"Unsafe command '{node_type}' detected inside the query.",
                )

        # Normalize statement syntax
        try:
            normalized_sql = expression.sql(dialect=self.dialect, pretty=False)
        except Exception as e:
            normalized_sql = cleaned_sql
            logger.warning(f"Could not format normalized SQL expression: {e}")

        duration = (time.perf_counter() - start_time) * 1000
        logger.info(
            "SQL safety validation passed successfully.",
            extra={
                "duration_ms": duration,
                "statement_type": statement_type,
                "query_length": len(cleaned_sql),
            },
        )

        return SQLValidationResult(
            valid=True,
            normalized_sql=normalized_sql,
            statement_type=statement_type,
        )

    def assert_valid(self, sql: str) -> None:
        """Helper assertion method raising custom exceptions if validation fails."""
        result = self.validate(sql)
        if not result.valid:
            reason = result.reason or "Unknown safety violation."
            if "parsing failed" in reason or "Parser failed" in reason:
                raise SQLParsingException(reason)
            else:
                raise UnsafeSQLException(reason)
