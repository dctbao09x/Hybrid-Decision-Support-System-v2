# backend/kb/database.py
"""
Database connection and session management (Production-ready)
"""

import os
import threading
from contextlib import contextmanager
from typing import Iterator
from typing import Generator
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker, Session

# ================= CONFIG =================

DB_ENV = os.getenv("APP_ENV", "dev")  # dev | test | prod

DATABASE_URL = os.getenv(
    "DATABASE_URL",
    "sqlite:///./career_kb.db" if DB_ENV == "dev"
    else "sqlite:///./career_kb_prod.db"
)

SQL_ECHO = os.getenv("SQL_ECHO", "false").lower() == "true"


# ================= ENGINE =================

engine_kwargs = {
    "echo": SQL_ECHO,
    "future": True,
    "pool_pre_ping": True
}

# SQLite special config
if DATABASE_URL.startswith("sqlite"):
    engine_kwargs["connect_args"] = {
        "check_same_thread": False
    }
else:
    # For PostgreSQL/MySQL
    engine_kwargs.update({
        "pool_size": int(os.getenv("DB_POOL_SIZE", 10)),
        "max_overflow": int(os.getenv("DB_MAX_OVERFLOW", 20)),
        "pool_timeout": 30,
        "pool_recycle": 1800
    })


engine = create_engine(
    DATABASE_URL,
    **engine_kwargs
)

_schema_checked = False
_schema_lock = threading.Lock()


def _get_existing_columns(conn, table_name: str) -> set[str]:
    rows = conn.execute(text(f"PRAGMA table_info({table_name})")).mappings().all()
    return {str(row["name"]) for row in rows}


def _ensure_columns(conn, table_name: str, required_columns: dict[str, str]) -> None:
    existing_columns = _get_existing_columns(conn, table_name)
    for column_name, ddl in required_columns.items():
        if column_name not in existing_columns:
            conn.execute(text(f"ALTER TABLE {table_name} ADD COLUMN {ddl}"))


def ensure_legacy_schema_columns() -> None:
    global _schema_checked

    if _schema_checked:
        return

    with _schema_lock:
        if _schema_checked:
            return

        if not DATABASE_URL.startswith("sqlite"):
            _schema_checked = True
            return

        with engine.begin() as conn:
            _ensure_columns(conn, "careers", {
                "code": "code VARCHAR(50)",
                "level": "level VARCHAR(50)",
                "market_tags": "market_tags JSON",
                "version": "version INTEGER NOT NULL DEFAULT 1",
                "status": "status VARCHAR(20) NOT NULL DEFAULT 'active'",
            })

            _ensure_columns(conn, "skills", {
                "code": "code VARCHAR(50)",
                "level_map": "level_map JSON",
                "related_skills": "related_skills JSON",
                "version": "version INTEGER NOT NULL DEFAULT 1",
                "status": "status VARCHAR(20) NOT NULL DEFAULT 'active'",
            })

        _schema_checked = True


# ================= SESSION =================

SessionLocal = sessionmaker(
    bind=engine,
    autocommit=False,
    autoflush=False,
    expire_on_commit=False,
    class_=Session
)


# ================= DEPENDENCY =================

def get_db() -> Generator[Session, None, None]:
    """
    FastAPI dependency
    """
    ensure_legacy_schema_columns()
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


@contextmanager
def get_db_context() -> Iterator[Session]:

    """
    Context manager for scripts / CLI
    """
    db = SessionLocal()

    try:
        yield db
        db.commit()

    except Exception:
        db.rollback()
        raise

    finally:
        db.close()


# ================= INIT / HEALTH =================

def check_db_connection() -> bool:
    """
    Check DB health
    """
    try:
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
        return True
    except Exception:
        return False


def init_db() -> None:
    """
    Create all tables
    """
    from .models import Base

    if not check_db_connection():
        raise RuntimeError("Database connection failed")

    Base.metadata.create_all(bind=engine)

    print("✓ Database initialized")


def reset_db(confirm: bool = False) -> None:
    """
    Reset DB (dangerous)
    """
    if not confirm:
        raise RuntimeError("reset_db(confirm=True) required")

    from .models import Base

    Base.metadata.drop_all(bind=engine)
    Base.metadata.create_all(bind=engine)

    print("✓ Database reset completed")
