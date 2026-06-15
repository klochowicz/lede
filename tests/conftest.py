import pytest


@pytest.fixture
def db_access(db):
    """Alias so tests read intent: this test touches the database."""
    return db
