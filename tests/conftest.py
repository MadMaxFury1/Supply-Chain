import pytest

from control_tower.db.session import get_session, use_test_db


@pytest.fixture()
def db(tmp_path):
    """Fresh isolated SQLite DB per test."""
    use_test_db(f"sqlite:///{tmp_path / 'test.db'}")
    with get_session() as session:
        yield session
