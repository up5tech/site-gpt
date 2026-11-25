import logging

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from site_gpt.app.core.config import DB_URL, SQL_ECHO
from site_gpt.app.core.logging import log_exception

if DB_URL is None:
    raise ValueError("DB_URL is not set")

engine = create_engine(DB_URL, echo=SQL_ECHO)

SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False)


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


def get_db():
    """Dependency to get a database session."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
