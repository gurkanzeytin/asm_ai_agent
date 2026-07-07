from sqlalchemy.orm import DeclarativeBase


class Base(DeclarativeBase):
    """Declarative Base class for all database ORM models.

    Serves as the centralized metadata registry for database tables,
    enabling integration with database migration tools like Alembic.
    """

    pass
