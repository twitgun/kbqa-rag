"""数据库连接（MySQL 8 / PyMySQL）。"""

from __future__ import annotations

from collections.abc import Iterator

from sqlalchemy import create_engine
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from kbqa.settings import settings

engine = create_engine(
    settings.database_url,
    pool_pre_ping=True,      # 断线自动重连，避免 MySQL 8h 超时后第一个请求必失败
    pool_recycle=3600,
    future=True,
)

SessionLocal = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)


class Base(DeclarativeBase):
    pass


def get_db() -> Iterator[Session]:
    db = SessionLocal()
    try:
        yield db
        db.commit()
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


def ping() -> tuple[bool, str]:
    """健康检查用：能执行 SELECT 1 即视为可用。"""
    try:
        with engine.connect() as conn:
            conn.exec_driver_sql("SELECT 1")
        return True, engine.url.render_as_string(hide_password=True)
    except Exception as exc:  # noqa: BLE001
        return False, f"{type(exc).__name__}: {exc}"
