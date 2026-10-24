from collections.abc import Generator
from sqlalchemy.pool import NullPool
from sqlmodel import Session, SQLModel, create_engine

from config.settings import settings

raw_url = settings.DATABASE_URL.get_secret_value().strip()
if raw_url.startswith("postgres://"):
    database_url = raw_url.replace("postgres://", "postgresql+psycopg://", 1)
elif raw_url.startswith("postgresql://"):
    database_url = raw_url.replace("postgresql://", "postgresql+psycopg://", 1)
else:
    database_url = raw_url or "sqlite:///:memory:"

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
