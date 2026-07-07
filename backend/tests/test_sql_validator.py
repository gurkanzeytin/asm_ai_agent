import pytest

from app.sql_validator import (
    SQLParsingException,
    SQLValidationResult,
    SQLValidator,
    UnsafeSQLException,
)


def test_valid_select_statements():
    validator = SQLValidator()

    # Simple Select
    res1 = validator.validate("SELECT * FROM users;")
    assert res1.valid is True
    assert res1.statement_type == "Select"
    assert res1.normalized_sql == "SELECT * FROM users"

    # Select with Join
    res2 = validator.validate(
        "SELECT u.name, o.total FROM users u JOIN orders o ON u.id = o.user_id WHERE o.status = 'completed';"
    )
    assert res2.valid is True
    assert "JOIN" in res2.normalized_sql

    # Select with subquery
    res3 = validator.validate("SELECT name FROM (SELECT * FROM users WHERE age > 21) WHERE id = 1;")
    assert res3.valid is True

    # Select with CTE (WITH clause)
    res4 = validator.validate(
        "WITH active_users AS (SELECT * FROM users WHERE status = 'active') SELECT * FROM active_users;"
    )
    assert res4.valid is True
    assert res4.statement_type in ("Select", "With")


def test_select_with_union():
    validator = SQLValidator()
    res = validator.validate("SELECT id FROM users UNION SELECT id FROM customers;")
    assert res.valid is True
    assert res.statement_type == "Union"


def test_unsafe_sql_rejection():
    validator = SQLValidator()

    # INSERT
    res = validator.validate("INSERT INTO users (name) VALUES ('Alice');")
    assert res.valid is False
    assert "Unsafe command 'Insert'" in res.reason or "Unsafe root statement type 'Insert'" in res.reason

    # UPDATE
    res = validator.validate("UPDATE users SET status = 'inactive' WHERE id = 1;")
    assert res.valid is False
    assert "Unsafe command 'Update'" in res.reason or "Unsafe root statement type 'Update'" in res.reason

    # DELETE
    res = validator.validate("DELETE FROM users WHERE id = 1;")
    assert res.valid is False
    assert "Unsafe command 'Delete'" in res.reason or "Unsafe root statement type 'Delete'" in res.reason

    # DROP
    res = validator.validate("DROP TABLE users;")
    assert res.valid is False
    assert "Unsafe root statement type 'Drop'" in res.reason

    # ALTER
    res = validator.validate("ALTER TABLE users ADD COLUMN age INT;")
    assert res.valid is False
    assert "Unsafe root statement type 'Alter'" in res.reason

    # CREATE
    res = validator.validate("CREATE TABLE logs (id INT);")
    assert res.valid is False
    assert "Unsafe root statement type 'Create'" in res.reason

    # TRUNCATE
    res = validator.validate("TRUNCATE TABLE logs;")
    assert res.valid is False
    assert "Unsafe root statement type 'TruncateTable'" in res.reason or "Unsafe root statement type 'Command'" in res.reason

    # MERGE
    res = validator.validate("MERGE INTO target USING source ON (id) WHEN MATCHED THEN UPDATE SET x = y;")
    assert res.valid is False
    assert "Unsafe root statement type 'Merge'" in res.reason

    # REPLACE (as a statement, not string function)
    res = validator.validate("REPLACE INTO users (id, name) VALUES (1, 'Bob');")
    assert res.valid is False
    # sqlglot parses REPLACE INTO as an Insert statement or falls back to Command depending on dialect
    assert (
        "Unsafe command 'Insert'" in res.reason
        or "Unsafe root statement type 'Insert'" in res.reason
        or "Unsafe root statement type 'Command'" in res.reason
    )


def test_transaction_control_rejection():
    validator = SQLValidator()

    assert validator.validate("BEGIN TRANSACTION;").valid is False
    assert validator.validate("COMMIT;").valid is False
    assert validator.validate("ROLLBACK;").valid is False


def test_multiple_statements_rejection():
    validator = SQLValidator()
    res = validator.validate("SELECT * FROM users; SELECT * FROM logs;")
    assert res.valid is False
    assert "Multiple SQL statements" in res.reason


def test_malformed_sql_handling():
    validator = SQLValidator()
    res = validator.validate("SELECT FROM WHERE LIMIT;")
    assert res.valid is False
    assert "SQL syntax parsing failed" in res.reason
    assert len(res.warnings) > 0


def test_empty_sql_handling():
    validator = SQLValidator()
    res = validator.validate("   ")
    assert res.valid is False
    assert "Query is empty." in res.reason


def test_assertion_methods():
    validator = SQLValidator()

    # Valid Select should not raise anything
    validator.assert_valid("SELECT * FROM users WHERE id = 1")

    # Unsafe should raise UnsafeSQLException
    with pytest.raises(UnsafeSQLException):
        validator.assert_valid("DELETE FROM users;")

    # Malformed should raise SQLParsingException
    with pytest.raises(SQLParsingException):
        validator.assert_valid("SELECT * FROM FROM WHERE")


def test_logging_and_metrics(caplog):
    validator = SQLValidator()
    with caplog.at_level("INFO"):
        validator.validate("SELECT * FROM users WHERE status = 'active';")
        log_messages = [rec.message for rec in caplog.records]
        assert "SQL safety validation started." in log_messages
        assert "SQL safety validation passed successfully." in log_messages

        # Verify extra log parameters
        passed_record = next(
            rec
            for rec in caplog.records
            if rec.message == "SQL safety validation passed successfully."
        )
        assert passed_record.statement_type == "Select"
        assert hasattr(passed_record, "duration_ms")
        assert passed_record.query_length > 0
