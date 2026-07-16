import re

import sqlglot.expressions as exp

# AST expression types that perform database updates, structure modifications, or transaction controls
FORBIDDEN_AST_NODES = (
    exp.Insert,
    exp.Update,
    exp.Delete,
    exp.Drop,
    exp.Alter,
    exp.Create,
    exp.Merge,
    exp.Command,
    exp.Transaction,
    exp.Commit,
    exp.Rollback,
    exp.Grant,
    exp.Revoke,
    exp.TruncateTable,
    exp.Use,
    exp.Execute,
    exp.Into,
)

# Allowed root level statement types that represent data retrieval queries
ALLOWED_ROOT_NODES = (
    exp.Select,
    exp.Union,
    exp.SetOperation,
    exp.Subquery,
)

# Function invocations that reach outside the database boundary (ad-hoc remote
# access, dynamic SQL). Compared case-insensitively against parsed function names.
FORBIDDEN_FUNCTION_NAMES = frozenset(
    {
        "openrowset",
        "opendatasource",
        "openquery",
        "sp_executesql",
        "xp_cmdshell",
    }
)

# Defense-in-depth keyword scan (AST validation is the primary control).
# Applied to SQL text with string literals stripped, using word boundaries.
FORBIDDEN_KEYWORD_PATTERN = re.compile(
    r"\b("
    r"insert|update|delete|merge|drop|alter|create|truncate"
    r"|exec|execute|grant|revoke|deny|dbcc|backup|restore"
    r"|openrowset|opendatasource|sp_executesql|xp_cmdshell"
    r")\b",
    re.IGNORECASE,
)


def strip_string_literals(sql: str) -> str:
    """Removes single-quoted string literal contents to avoid keyword false positives."""
    return re.sub(r"'(?:[^']|'')*'", "''", sql)
