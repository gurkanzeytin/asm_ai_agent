import logging
import time

import sqlglot
import sqlglot.expressions as exp
from sqlglot.errors import ParseError

from app.core.config import settings
from app.sql_validator.exceptions import SQLParsingException, UnsafeSQLException
from app.sql_validator.interfaces import ISQLValidator
from app.sql_validator.models import SQLValidationResult
from app.sql_validator.rules import (
    ALLOWED_ROOT_NODES,
    FORBIDDEN_AST_NODES,
    FORBIDDEN_FUNCTION_NAMES,
    FORBIDDEN_KEYWORD_PATTERN,
    strip_string_literals,
)

logger = logging.getLogger(__name__)


def normalize_object_name(name: str, default_schema: str) -> str:
    """Normalizes an SQL object identifier to a canonical 'schema.name' lowercase form.

    Strips SQL Server brackets and quote characters, then qualifies unqualified
    names with the configured default schema.
    """
    cleaned = name.replace("[", "").replace("]", "").replace('"', "").replace("`", "").strip()
    parts = [part.strip() for part in cleaned.split(".") if part.strip()]
    if len(parts) == 1:
        parts = [default_schema, parts[0]]
    return ".".join(parts).lower()


class SQLValidator(ISQLValidator):
    """AST-based SQL validator validating query safety and read-only status using sqlglot."""

    def __init__(
        self,
        dialect: str | None = None,
        allowed_objects: list[str] | None = None,
        default_schema: str | None = None,
    ):
        self.dialect = dialect or getattr(settings, "SQL_DIALECT", "sqlite")
        self._allowed_objects = allowed_objects
        self._default_schema = default_schema

    @property
    def default_schema(self) -> str:
        if self._default_schema is not None:
            return self._default_schema
        return getattr(settings, "DATABASE_SCHEMA", "dbo") or "dbo"

    @property
    def allowed_objects(self) -> set[str]:
        """Canonical 'schema.name' whitelist. Empty set disables object restriction."""
        raw = (
            self._allowed_objects
            if self._allowed_objects is not None
            else getattr(settings, "DATABASE_ALLOWED_OBJECTS", [])
        )
        return {normalize_object_name(item, self.default_schema) for item in raw if item}

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
            if isinstance(node, (exp.Anonymous, exp.Func)):
                func_name = (node.name or "").lower()
                if func_name in FORBIDDEN_FUNCTION_NAMES:
                    logger.error(f"Forbidden function invocation detected: {func_name}.")
                    return SQLValidationResult(
                        valid=False,
                        statement_type=statement_type,
                        reason=f"Unsafe function '{func_name}' detected inside the query.",
                    )

        # Defense-in-depth keyword scan (AST validation above is the primary control)
        keyword_match = FORBIDDEN_KEYWORD_PATTERN.search(strip_string_literals(cleaned_sql))
        if keyword_match:
            logger.error(f"Forbidden keyword detected in SQL text: {keyword_match.group(0)}.")
            return SQLValidationResult(
                valid=False,
                statement_type=statement_type,
                reason=f"Unsafe keyword '{keyword_match.group(0)}' detected inside the query.",
            )

        # Enforce the configured queryable-object whitelist (read-only boundary)
        object_violation = self._check_allowed_objects(expression)
        if object_violation:
            logger.error(f"Object whitelist violation: {object_violation}")
            return SQLValidationResult(
                valid=False,
                statement_type=statement_type,
                reason=object_violation,
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

    def _check_allowed_objects(self, expression: exp.Expression) -> str | None:
        """Verifies that every referenced table/view is inside the configured whitelist.

        Returns a rejection reason string, or None when the query is acceptable.
        An empty whitelist (local development) disables the restriction.
        """
        allowed = self.allowed_objects
        if not allowed:
            return None

        cte_names = {
            cte.alias_or_name.lower()
            for cte in expression.find_all(exp.CTE)
            if cte.alias_or_name
        }

        for table in expression.find_all(exp.Table):
            # CTE references are derived sources, not physical objects.
            if not table.db and table.name.lower() in cte_names:
                continue
            if table.catalog:
                return (
                    f"Cross-database or linked-server reference "
                    f"'{table.catalog}.{table.db}.{table.name}' is not permitted."
                )
            qualified = normalize_object_name(
                f"{table.db}.{table.name}" if table.db else table.name,
                self.default_schema,
            )
            if qualified not in allowed:
                return (
                    f"Reference to object '{table.db + '.' if table.db else ''}{table.name}' "
                    f"is outside the allowed object list."
                )
        return None

    def validate_schema_identifiers(self, sql: str, database_context) -> list[str]:
        """Compares SQL identifiers against the retrieved schema context.

        Returns human-readable issues for tables or columns that do not exist in the
        retrieved DatabaseContext. CTEs, subquery aliases, and SELECT aliases are
        treated as legitimate derived sources. Returns an empty list when the SQL
        cannot be parsed (syntax problems are reported by validate()).
        """
        if database_context is None:
            return []
        try:
            expression = sqlglot.parse_one(sql.strip().rstrip(";"), read=self.dialect)
        except Exception:
            return []
        if expression is None:
            return []

        known_columns: dict[str, set[str] | None] = {}
        for table in database_context.tables:
            columns = {column.name.lower() for column in table.columns}
            known_columns[table.name.lower()] = columns
            # Register the unqualified name too when metadata is schema-qualified.
            known_columns.setdefault(table.name.split(".")[-1].lower(), columns)
        for view in database_context.views:
            view_columns = {column.name.lower() for column in view.columns} or None
            known_columns.setdefault(view.name.lower(), view_columns)
            known_columns.setdefault(view.name.split(".")[-1].lower(), view_columns)

        derived_sources = {
            cte.alias_or_name.lower()
            for cte in expression.find_all(exp.CTE)
            if cte.alias_or_name
        }
        for subquery in expression.find_all(exp.Subquery):
            if subquery.alias:
                derived_sources.add(subquery.alias.lower())

        issues: list[str] = []

        def add_issue(issue: str) -> None:
            if issue not in issues:
                issues.append(issue)

        alias_to_table: dict[str, str] = {}
        for table in expression.find_all(exp.Table):
            table_name = table.name.lower()
            alias = (table.alias or table.name).lower()
            alias_to_table[alias] = table_name
            if table_name not in known_columns and table_name not in derived_sources:
                add_issue(f"unknown table '{table.name}'")

        select_aliases = {
            alias_expr.alias.lower()
            for alias_expr in expression.find_all(exp.Alias)
            if alias_expr.alias
        }

        for column in expression.find_all(exp.Column):
            if isinstance(column.this, exp.Star):
                continue
            column_name = column.name.lower()
            if not column_name or column_name == "*":
                continue
            qualifier = (column.table or "").lower()
            if qualifier:
                source = alias_to_table.get(qualifier, qualifier)
                if source in derived_sources:
                    continue
                columns = known_columns.get(source)
                if columns is None:
                    # Unknown table (already reported) or view without column metadata.
                    continue
                if column_name not in columns:
                    add_issue(f"unknown column '{qualifier}.{column.name}'")
            else:
                if column_name in select_aliases or derived_sources:
                    continue
                referenced = {
                    source for source in alias_to_table.values() if known_columns.get(source)
                }
                candidate_sets = (
                    [known_columns[table] for table in referenced]
                    if referenced
                    else [columns for columns in known_columns.values() if columns]
                )
                searchable_columns: set[str] = set().union(*candidate_sets) if candidate_sets else set()
                if searchable_columns and column_name not in searchable_columns:
                    add_issue(f"unknown column '{column.name}'")

        return issues

    def assert_valid(self, sql: str) -> None:
        """Helper assertion method raising custom exceptions if validation fails."""
        result = self.validate(sql)
        if not result.valid:
            reason = result.reason or "Unknown safety violation."
            if "parsing failed" in reason or "Parser failed" in reason:
                raise SQLParsingException(reason)
            else:
                raise UnsafeSQLException(reason)
