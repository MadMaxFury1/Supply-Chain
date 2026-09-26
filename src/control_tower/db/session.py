from contextlib import contextmanager

from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from control_tower.config import DB_PATH
from control_tower.db.models import Base

_engine = None
_SessionLocal = None


def get_engine():
    global _engine
    if _engine is None:
        DB_PATH.parent.mkdir(parents=True, exist_ok=True)
        _engine = create_engine(f"sqlite:///{DB_PATH}", future=True)
    return _engine


def init_db(drop_existing: bool = False) -> None:
    engine = get_engine()
    if drop_existing:
        Base.metadata.drop_all(engine)
    Base.metadata.create_all(engine)


def use_test_db(url: str) -> None:
    """Point the module at an isolated database (e.g. a temp file), for tests."""
    global _engine, _SessionLocal
    _engine = create_engine(url, future=True)
    _SessionLocal = sessionmaker(bind=_engine, future=True)
    Base.metadata.create_all(_engine)


@contextmanager
def get_session() -> Session:
    global _SessionLocal
    if _SessionLocal is None:
        _SessionLocal = sessionmaker(bind=get_engine(), future=True)
    session = _SessionLocal()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()
