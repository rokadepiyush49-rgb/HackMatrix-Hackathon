"""Database engine, session factory and declarative base."""

from collections.abc import Iterator
from contextlib import contextmanager

from sqlalchemy import MetaData, create_engine
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from app.core.config import get_settings

NAMING = {
    "ix": "ix_%(column_0_label)s",
    "uq": "uq_%(table_name)s_%(column_0_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
    "pk": "pk_%(table_name)s",
}


class Base(DeclarativeBase):
    metadata = MetaData(naming_convention=NAMING)


def _engine():
    s = get_settings()
    connect_args = {"application_name": f"sutra-{s.env}"}
    if s.db_statement_timeout_ms:
        connect_args["options"] = f"-c statement_timeout={s.db_statement_timeout_ms}"
    # pre_ping survives RDS failovers and idle-connection reaping by RDS Proxy; recycle keeps
    # connections younger than typical proxy/NAT idle timeouts.
    return create_engine(s.database_url, pool_pre_ping=True, pool_size=s.db_pool_size,
                         max_overflow=s.db_max_overflow, pool_recycle=1800, connect_args=connect_args)


engine = _engine()
SessionLocal = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)


def get_db() -> Iterator[Session]:
    """FastAPI dependency: one session per request."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


@contextmanager
def session_scope() -> Iterator[Session]:
    """Transactional scope for scripts and the pipeline."""
    db = SessionLocal()
    try:
        yield db
        db.commit()
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()
