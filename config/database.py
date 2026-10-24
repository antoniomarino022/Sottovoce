from collections.abc import Generator
from sqlalchemy.pool import NullPool
from sqlmodel import Session, SQLModel, create_engine

from config.settings import settings

database_url = settings.DATABASE_URL.get_secret_value()
is_postgres = database_url.startswith("postgresql")

connect_args = {"connect_timeout": 3} if is_postgres else {}

if is_postgres and settings.is_serverless:
    pool_kwargs = {"poolclass": NullPool}
elif is_postgres:
    pool_kwargs = {"pool_size": 5, "max_overflow": 10, "pool_recycle": 240}
else:
    pool_kwargs = {}

engine = create_engine(
    database_url,
    echo=False,
    connect_args=connect_args,
    **pool_kwargs,
)


def init_db() -> None:
    """Create all database tables defined in SQLModel metadata."""
    import src.models  # noqa: F401

    SQLModel.metadata.create_all(engine)


def get_session() -> Generator[Session, None, None]:
    """FastAPI dependency that yields a database session per request."""
    with Session(engine, expire_on_commit=False) as session:
        yield session
