import logging

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from site_gpt.app.core.config import (
    DB_MAX_OVERFLOW,
    DB_POOL_RECYCLE_SECONDS,
    DB_POOL_SIZE,
    DB_POOL_TIMEOUT_SECONDS,
    DB_URL,
    SQL_ECHO,
)
from site_gpt.app.core.logging import log_exception

if DB_URL is None:
    raise ValueError("DB_URL is not set")


def engine_options(
    url: str,
    *,
    pool_size: int = DB_POOL_SIZE,
    max_overflow: int = DB_MAX_OVERFLOW,
    pool_timeout: int = DB_POOL_TIMEOUT_SECONDS,
    pool_recycle: int = DB_POOL_RECYCLE_SECONDS,
) -> dict:
    """The `create_engine` kwargs for `url` (V6-23).

    A networked database gets an explicit pool: the size bounds how many
    connections one process can hold, the overflow what it may open above that
    under a burst, the timeout how long a request waits for one, and the recycle
    age so a connection killed by a proxy or a failover is replaced before it is
    handed to a request (`pool_pre_ping` then covers anything that still slips
    through). The defaults are sized for a small deployment — see
    `pool_ceiling` — and every process has its own pool, so the deployment's cost
    multiplies by the number of processes.

    SQLite keeps SQLAlchemy's default pool: an in-memory test database is one
    shared connection under `StaticPool`, and a file database has no server side
    to protect, so pool sizing there would only change test behaviour.
    """
    options: dict = {"echo": SQL_ECHO}
    if str(url).startswith("sqlite"):
        return options
    options.update(
        pool_pre_ping=True,
        pool_size=pool_size,
        max_overflow=max_overflow,
        pool_timeout=pool_timeout,
        pool_recycle=pool_recycle,
    )
    return options


def pool_ceiling(
    instances: int,
    *,
    pool_size: int = DB_POOL_SIZE,
    max_overflow: int = DB_MAX_OVERFLOW,
) -> int:
    """Worst-case server connections `instances` processes can open (V6-23).

    Each process holds up to `pool_size` idle connections and may open
    `max_overflow` more under load, so this is the number to compare with the
    database's `max_connections` before adding a replica or raising the pool.
    Migrations and an operator shell need headroom on top of it.
    """
    if instances < 0:
        raise ValueError("instances cannot be negative")
    return instances * (pool_size + max_overflow)


def dispose_engine() -> bool:
    """Close every pooled connection; never raises (V6-23).

    Called by the API's and the worker's shutdown: the process is leaving, and a
    pooled connection left behind is a server-side backend that only times out
    on its own — which a rolling deploy then stacks up. Best-effort, because a
    failure here must not turn a clean stop into a failed one; the pool
    reconnects lazily if anything still uses the engine afterwards, which is why
    this is safe in tests that share the module-level engine.
    """
    try:
        engine.dispose()
    except Exception as e:  # noqa: BLE001 - shutdown must not fail here
        log_exception("db.dispose_failed", e, level=logging.WARNING)
        return False
    return True


engine = create_engine(DB_URL, **engine_options(DB_URL))

SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False)


def get_db():
    """Dependency to get a database session."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
