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
)

# Allowed root level statement types that represent data retrieval queries
ALLOWED_ROOT_NODES = (
    exp.Select,
    exp.Union,
    exp.SetOperation,
    exp.Subquery,
)
