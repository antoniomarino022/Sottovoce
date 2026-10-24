from logging.config import fileConfig

from alembic import context
from sqlmodel import SQLModel

from config.database import engine
from config.settings import settings
import src.models  # noqa: F401 - ensure all models are registered in metadata

# this is the Alembic Config object, which provides
# access to the values within the .ini file in use.
config = context.config

# Interpret the config file for Python logging.
# This line sets up loggers basically.
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

# Target metadata for autogenerate support
target_metadata = SQLModel.metadata

# Only manage Hot-Mic application tables, ignore tables from other apps in the same DB
HOTMIC_TABLES = {
    "users",
    "confessions",
    "reactions",
    "reports",
    "coin_transactions",
    "poll_votes",
}


def include_object(object, name, type_, reflected, compare_to):
    """Filter to ensure Alembic only manages Hot-Mic tables."""
    if type_ == "table":
        return name in HOTMIC_TABLES
    return True


def run_migrations_offline() -> None:
    """Run migrations in 'offline' mode."""
    url = settings.DATABASE_URL.get_secret_value()
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        compare_type=True,
        include_object=include_object,
    )

    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    """Run migrations in 'online' mode using application engine."""
    with engine.connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            compare_type=True,
            include_object=include_object,
        )

        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
