from __future__ import annotations

from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from . import config

engine = create_engine(config.DATABASE_URL, pool_pre_ping=True, pool_size=5, max_overflow=5,
                       connect_args={"options": "-c statement_timeout=30000 -c idle_in_transaction_session_timeout=60000"})
SessionLocal = sessionmaker(bind=engine, expire_on_commit=False)


def get_db():
    db: Session = SessionLocal()
    try:
        yield db
    finally:
        db.close()
