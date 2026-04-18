from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from site_gpt.app.core.config import DB_URL

engine = create_engine(DB_URL, echo=True)

SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False)


def get_db():
    """Dependency to get a database session."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
