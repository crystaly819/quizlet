from __future__ import annotations

from contextlib import contextmanager
from typing import Iterator

from sqlalchemy import create_engine, text
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, declarative_base, sessionmaker

Base = declarative_base()


_engine: Engine | None = None
_session_local: sessionmaker[Session] | None = None
_configured_url: str | None = None


def configure_database(database_url: str) -> None:
    global _engine, _session_local, _configured_url

    if _engine is not None and _configured_url == database_url:
        return

    connect_args = {"check_same_thread": False} if database_url.startswith("sqlite") else {}
    _engine = create_engine(database_url, future=True, connect_args=connect_args)
    _session_local = sessionmaker(
        bind=_engine,
        autoflush=False,
        autocommit=False,
        expire_on_commit=False,
    )
    _configured_url = database_url


def get_engine() -> Engine:
    if _engine is None:
        raise RuntimeError("Database has not been configured.")
    return _engine


def get_session() -> Session:
    if _session_local is None:
        raise RuntimeError("Database has not been configured.")
    return _session_local()


@contextmanager
def session_scope() -> Iterator[Session]:
    session = get_session()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


def ensure_sqlite_schema() -> None:
    engine = get_engine()
    if engine.dialect.name != "sqlite":
        return

    required_columns = {
        "questions": {
            "question_kind": "TEXT NOT NULL DEFAULT 'multiple_choice'",
            "answer_text": "TEXT",
            "explanation_text": "TEXT",
            "choices_json": "TEXT",
            "manual_reviewed": "BOOLEAN NOT NULL DEFAULT 0",
        }
    }

    with engine.begin() as connection:
        for table_name, columns in required_columns.items():
            table_info = connection.execute(text(f"PRAGMA table_info({table_name})")).mappings().all()
            existing_columns = {row["name"] for row in table_info}
            for column_name, column_ddl in columns.items():
                if column_name in existing_columns:
                    continue
                connection.execute(text(f"ALTER TABLE {table_name} ADD COLUMN {column_name} {column_ddl}"))


def init_db() -> None:
    Base.metadata.create_all(bind=get_engine())
    ensure_sqlite_schema()
