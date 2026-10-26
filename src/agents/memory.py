import logging
from contextlib import asynccontextmanager
from typing import Any, AsyncGenerator, Optional
import uuid

from langchain_core.runnables import RunnableConfig
from langgraph.checkpoint.base import BaseCheckpointSaver
from langgraph.checkpoint.memory import MemorySaver
from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver
from psycopg.rows import dict_row
from psycopg_pool import AsyncConnectionPool

from config.settings import settings

logger = logging.getLogger(__name__)

_pool: Optional[AsyncConnectionPool] = None
_saver: Optional[Any] = None


async def init_checkpointer() -> AsyncPostgresSaver:
    """Open the pool and create tables once. Call at app startup."""
    global _pool, _saver
    if _saver is not None:
        return _saver

    conninfo = settings.DATABASE_URL.get_secret_value().strip().replace(
        "postgresql+psycopg://", "postgresql://", 1
    )
    _pool = AsyncConnectionPool(
        conninfo=conninfo,
        min_size=0 if settings.is_serverless else 1,
        max_size=2 if settings.is_serverless else 5,
        kwargs={"autocommit": True, "prepare_threshold": 0, "row_factory": dict_row},
        open=False,
    )
    await _pool.open(wait=True, timeout=5)
    _saver = AsyncPostgresSaver(_pool)  # type: ignore[arg-type]
    if not settings.is_serverless:
        await _saver.setup()
    return _saver


async def close_checkpointer() -> None:
    """Close the pool. Call at app shutdown."""
    global _pool, _saver
    if _pool is not None:
        await _pool.close()
    _pool = _saver = None


def reset_checkpointer_for_testing(custom_saver: Optional[Any] = None) -> None:
    """Reset the checkpointer for tests and clear compiled graph cache."""
    global _saver
    _saver = custom_saver or MemorySaver()
    try:
        from src.agents.graph import reset_compiled_graphs
        reset_compiled_graphs()
    except ImportError:
        logger.debug("graph module not importable; skipping compiled graph reset.")


def get_checkpointer() -> Any:
    global _saver
    if _saver is None:
        logger.warning(
            "Checkpointer not initialised: falling back to in-memory saver "
            "(state will NOT persist). Call init_checkpointer() at startup."
        )
        _saver = MemorySaver()
    return _saver


@asynccontextmanager
async def get_async_checkpointer() -> AsyncGenerator[Any, None]:
    """Compatibility wrapper: yields the shared saver, opens nothing."""
    yield get_checkpointer()


def get_thread_config(confession_id: Optional[int | str] = None) -> RunnableConfig:
    """Return isolated LangGraph thread config; generates a unique ephemeral ID if confession_id is None."""
    if confession_id is not None:
        thread_id = f"confession_{confession_id}"
    else:
        thread_id = f"confession_ephemeral_{uuid.uuid4().hex}"
    return {"configurable": {"thread_id": thread_id}}


async def get_confession_history(
    confession_id: Optional[int | str] = None,
) -> Optional[dict[str, Any]]:
    """Return persisted state values for a confession, or None."""
    tup = await get_checkpointer().aget_tuple(get_thread_config(confession_id))
    return tup.checkpoint.get("channel_values") if tup and tup.checkpoint else None


__all__ = [
    "init_checkpointer",
    "close_checkpointer",
    "reset_checkpointer_for_testing",
    "get_checkpointer",
    "get_async_checkpointer",
    "get_thread_config",
    "get_confession_history",
]