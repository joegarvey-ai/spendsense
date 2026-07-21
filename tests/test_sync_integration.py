"""Integration test for the sync pipeline with mocked SimpleFIN."""

import tempfile
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import MagicMock, patch

from src.db import get_connection, get_transaction_count, init_db
from src.sync import run_daily_sync


MOCK_ACCOUNTS_RESPONSE = {
    "errors": [],
    "accounts": [
        {
            "org": {"name": "Test Bank"},
            "id": "ACT-001",
            "name": "Checking",
            "currency": "USD",
            "balance": "5000.00",
            "available-balance": "5000.00",
            "balance-date": int(datetime.now(tz=timezone.utc).timestamp()),
            "transactions": [
                {
                    "id": "TXN-001",
                    "posted": int(datetime.now(tz=timezone.utc).timestamp()) - 86400,
                    "amount": "-52.34",
                    "description": "FRED MEYER #1234",
                    "pending": False,
                },
                {
                    "id": "TXN-002",
                    "posted": int(datetime.now(tz=timezone.utc).timestamp()) - 86400,
                    "amount": "-6.75",
                    "description": "STARBUCKS STORE 12345",
                    "pending": False,
                },
                {
                    "id": "TXN-003",
                    "posted": int(datetime.now(tz=timezone.utc).timestamp()) - 172800,
                    "amount": "3500.00",
                    "description": "PAYROLL DIRECT DEPOSIT",
                    "pending": False,
                },
            ],
        }
    ],
}


def _run_sync_with_mock(db_path, excel_path):
    """Run sync with all external dependencies mocked."""
    with patch("src.sync.settings") as mock_settings, \
         patch("src.sync.SimpleFINClient") as MockClient:

        mock_settings.SIMPLEFIN_USERNAME = "test_user"
        mock_settings.SIMPLEFIN_PASSWORD = "test_pass"
        mock_settings.SIMPLEFIN_BASE_URL = "https://example.com/simplefin"
        mock_settings.DB_PATH = db_path

        client_instance = MockClient.return_value
        client_instance.get_all_transactions.return_value = _flatten_transactions()
        client_instance.get_accounts_metadata.return_value = [
            {
                "id": "ACT-001",
                "institution": "Test Bank",
                "name": "Checking",
                "currency": "USD",
                "balance": "5000.00",
                "available_balance": "5000.00",
                "balance_date": int(datetime.now(tz=timezone.utc).timestamp()),
            }
        ]

        with patch("src.sync.init_db"), \
             patch("src.sync.get_connection") as mock_conn, \
             patch("src.sync.update_dashboard"):
            mock_conn.return_value = get_connection(db_path)
            return run_daily_sync(days_back=30, update_excel=False)


def _flatten_transactions():
    """Produce the same format SimpleFINClient.get_all_transactions returns."""
    txns = []
    for acct in MOCK_ACCOUNTS_RESPONSE["accounts"]:
        for txn in acct["transactions"]:
            txns.append({
                "account_id": acct["id"],
                "institution": acct["org"]["name"],
                "account_name": acct["name"],
                "currency": acct["currency"],
                "balance": acct["balance"],
                "available_balance": acct["available-balance"],
                "balance_date": acct["balance-date"],
                "id": f"{acct['id']}:{txn['id']}",
                "raw_txn_id": txn["id"],
                "posted": txn["posted"],
                "amount": txn["amount"],
                "description": txn["description"],
                "pending": txn["pending"],
            })
    return txns


def test_sync_inserts_transactions():
    """Sync should insert all fetched transactions with correct categorization."""
    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = Path(tmpdir) / "test.db"
        init_db(db_path)
        conn = get_connection(db_path)
        conn.execute(
            "INSERT INTO accounts (id, institution, name) VALUES ('ACT-001', 'Test Bank', 'Checking')"
        )
        conn.commit()
        conn.close()

        result = _run_sync_with_mock(db_path, Path(tmpdir) / "test.xlsx")

        assert result["fetched"] == 3
        assert result["new"] == 3
        assert result["updated"] == 0

        conn = get_connection(db_path)
        assert get_transaction_count(conn) == 3

        fred_meyer = conn.execute(
            "SELECT tier1, tier2 FROM transactions WHERE id = 'ACT-001:TXN-001'"
        ).fetchone()
        assert fred_meyer["tier1"] == "Essential"
        assert fred_meyer["tier2"] == "Groceries"

        payroll = conn.execute(
            "SELECT tier1, tier2 FROM transactions WHERE id = 'ACT-001:TXN-003'"
        ).fetchone()
        assert payroll["tier1"] == "Income"
        assert payroll["tier2"] == "Payroll"

        conn.close()


def test_sync_dedup_on_rerun():
    """Running sync twice with the same data should not create duplicates."""
    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = Path(tmpdir) / "test.db"
        init_db(db_path)
        conn = get_connection(db_path)
        conn.execute(
            "INSERT INTO accounts (id, institution, name) VALUES ('ACT-001', 'Test Bank', 'Checking')"
        )
        conn.commit()
        conn.close()

        result1 = _run_sync_with_mock(db_path, Path(tmpdir) / "test.xlsx")
        result2 = _run_sync_with_mock(db_path, Path(tmpdir) / "test.xlsx")

        assert result1["new"] == 3
        assert result2["new"] == 0
        assert result2["updated"] == 0

        conn = get_connection(db_path)
        assert get_transaction_count(conn) == 3
        conn.close()


if __name__ == "__main__":
    import pytest
    pytest.main([__file__, "-v"])
