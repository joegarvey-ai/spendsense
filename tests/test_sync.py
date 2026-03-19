"""Tests for the sync pipeline using mocked SimpleFIN responses."""

import sqlite3
import sys
import tempfile
from pathlib import Path
from unittest.mock import MagicMock, patch

sys.path.insert(0, str(Path(__file__).parent.parent))

from src.db import get_connection, get_transaction_count, init_db


def test_db_init_and_upsert():
    """Test database initialization and transaction upsert."""
    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = Path(tmpdir) / "test.db"
        init_db(db_path)
        conn = get_connection(db_path)

        # Insert an account first
        conn.execute(
            """INSERT INTO accounts (id, institution, name)
               VALUES ('ACT-001', 'My Credit Union', 'Checking')"""
        )
        conn.commit()

        # Insert a transaction
        from src.db import upsert_transaction

        txn = {
            "id": "ACT-001:TXN-001",
            "account_id": "ACT-001",
            "posted_at": "2026-03-14",
            "amount": -52.34,
            "description": "FRED MEYER #1234",
            "pending": 0,
            "tier1": "Essential",
            "tier2": "Groceries",
            "vendor": "Fred Meyer",
            "auto_categorized": 1,
            "month": "2026-03",
        }
        result = upsert_transaction(conn, txn)
        conn.commit()
        assert result == "new"

        # Upsert same ID → skipped
        result = upsert_transaction(conn, txn)
        assert result == "skipped"

        # Update pending status → updated
        txn["pending"] = 1
        result = upsert_transaction(conn, txn)
        conn.commit()
        assert result == "updated"

        assert get_transaction_count(conn) == 1
        conn.close()


def test_monthly_summary():
    """Test monthly summary aggregation."""
    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = Path(tmpdir) / "test.db"
        init_db(db_path)
        conn = get_connection(db_path)

        conn.execute(
            "INSERT INTO accounts (id, institution, name) VALUES ('A1', 'My Credit Union', 'Checking')"
        )
        conn.execute(
            """INSERT INTO transactions (id, account_id, posted_at, amount, description, pending, tier1, tier2, vendor, month)
               VALUES ('T1', 'A1', '2026-03-01', -50.0, 'FRED MEYER', 0, 'Essential', 'Groceries', 'Fred Meyer', '2026-03')"""
        )
        conn.execute(
            """INSERT INTO transactions (id, account_id, posted_at, amount, description, pending, tier1, tier2, vendor, month)
               VALUES ('T2', 'A1', '2026-03-05', -30.0, 'TRADER JOE', 0, 'Essential', 'Groceries', 'Trader Joes', '2026-03')"""
        )
        conn.execute(
            """INSERT INTO transactions (id, account_id, posted_at, amount, description, pending, tier1, tier2, vendor, month)
               VALUES ('T3', 'A1', '2026-03-10', -6.75, 'STARBUCKS', 0, 'Non-Essential', 'Dining Out', 'Starbucks', '2026-03')"""
        )
        conn.commit()

        from src.db import get_monthly_summary

        summary = get_monthly_summary(conn, "2026-03")
        assert len(summary) == 2  # Groceries + Dining Out

        groceries = [s for s in summary if s["tier2"] == "Groceries"][0]
        assert groceries["total"] == -80.0
        assert groceries["count"] == 2

        conn.close()


def test_override():
    """Test manual category override."""
    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = Path(tmpdir) / "test.db"
        init_db(db_path)
        conn = get_connection(db_path)

        conn.execute(
            "INSERT INTO accounts (id, institution, name) VALUES ('A1', 'My Credit Union', 'Checking')"
        )
        conn.execute(
            """INSERT INTO transactions (id, account_id, posted_at, amount, description, pending, tier1, tier2, month)
               VALUES ('T1', 'A1', '2026-03-01', -100.0, 'UNKNOWN STORE', 0, 'Non-Essential', 'Misc / Uncategorized', '2026-03')"""
        )
        conn.commit()

        from src.db import apply_override

        apply_override(conn, "T1", "Essential", "Medical", vendor="Pharmacy", reason="Prescription")

        row = conn.execute("SELECT tier1, tier2, vendor, auto_categorized FROM transactions WHERE id = 'T1'").fetchone()
        assert row[0] == "Essential"
        assert row[1] == "Medical"
        assert row[2] == "Pharmacy"
        assert row[3] == 0  # auto_categorized should be False

        conn.close()


if __name__ == "__main__":
    import pytest
    pytest.main([__file__, "-v"])
