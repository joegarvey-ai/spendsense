"""Shared test configuration and fixtures."""

import sys
import tempfile
from pathlib import Path

import pytest

# Ensure the project root is importable for all tests
sys.path.insert(0, str(Path(__file__).parent.parent))

from src.db import get_connection, init_db


@pytest.fixture
def tmp_db():
    """Provide a temporary SQLite database with full schema initialized."""
    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = Path(tmpdir) / "test.db"
        init_db(db_path)
        conn = get_connection(db_path)
        yield conn
        conn.close()


@pytest.fixture
def seeded_db(tmp_db):
    """Database with accounts seeded for testing."""
    tmp_db.execute(
        "INSERT INTO accounts (id, institution, name, friendly_name, account_type) "
        "VALUES ('A1', 'Test Bank', 'Checking', 'My Checking', 'checking')"
    )
    tmp_db.execute(
        "INSERT INTO accounts (id, institution, name, friendly_name, account_type) "
        "VALUES ('CC1', 'Card Issuer', 'Rewards Card', 'My CC', 'credit_card')"
    )
    tmp_db.commit()
    return tmp_db
