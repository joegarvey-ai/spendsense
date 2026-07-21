"""Tests for the Excel writer, focusing on the override round-trip."""

import tempfile
from pathlib import Path

from openpyxl import Workbook

from src.db import get_connection, init_db
from src.excel_writer import read_overrides_from_excel, TXN_LOG_HEADERS, TXN_LOG_START_ROW


def _create_test_db(tmpdir):
    """Create a test DB with schema and a sample transaction."""
    db_path = Path(tmpdir) / "test.db"
    init_db(db_path)
    conn = get_connection(db_path)

    conn.execute(
        "INSERT INTO accounts (id, institution, name) VALUES ('A1', 'Test Bank', 'Checking')"
    )
    conn.execute(
        """INSERT INTO transactions
           (id, account_id, posted_at, amount, description, pending, tier1, tier2, vendor, auto_categorized, month)
           VALUES ('TXN-001', 'A1', '2026-03-15', -42.50, 'SOME STORE #123', 0,
                   'Non-Essential', 'Shopping', 'Some Store', 1, '2026-03')"""
    )
    conn.commit()
    return db_path, conn


def _create_test_workbook(tmpdir, txn_id, tier1, tier2, reason, override_flag="Y"):
    """Create a minimal workbook with a Transaction Log sheet containing one overridden row."""
    wb = Workbook()
    ws = wb.active
    ws.title = "Transaction Log"

    for col_idx, header in enumerate(TXN_LOG_HEADERS, start=1):
        ws.cell(row=TXN_LOG_START_ROW, column=col_idx, value=header)

    data_row = TXN_LOG_START_ROW + 1
    ws.cell(row=data_row, column=1, value="2026-03-15")
    ws.cell(row=data_row, column=2, value="Some Store")
    ws.cell(row=data_row, column=3, value=-42.50)
    ws.cell(row=data_row, column=4, value="Test Bank - Checking")
    ws.cell(row=data_row, column=5, value=tier1)
    ws.cell(row=data_row, column=6, value=tier2)
    ws.cell(row=data_row, column=7, value="2026-03")
    ws.cell(row=data_row, column=8, value=reason)
    ws.cell(row=data_row, column=9, value=override_flag)
    ws.cell(row=data_row, column=10, value=txn_id)

    excel_path = Path(tmpdir) / "test_dashboard.xlsx"
    wb.save(str(excel_path))
    wb.close()
    return excel_path


def test_override_round_trip_preserves_vendor():
    """Override from Excel should set reason, NOT corrupt the vendor column."""
    with tempfile.TemporaryDirectory() as tmpdir:
        db_path, conn = _create_test_db(tmpdir)

        excel_path = _create_test_workbook(
            tmpdir,
            txn_id="TXN-001",
            tier1="Essential",
            tier2="Groceries",
            reason="Actually a grocery run",
        )

        count = read_overrides_from_excel(conn, excel_path)
        assert count == 1

        txn = conn.execute(
            "SELECT vendor, tier1, tier2 FROM transactions WHERE id = 'TXN-001'"
        ).fetchone()
        assert txn["tier1"] == "Essential"
        assert txn["tier2"] == "Groceries"
        assert txn["vendor"] is None or txn["vendor"] != "Actually a grocery run"

        override = conn.execute(
            "SELECT vendor, reason FROM overrides WHERE transaction_id = 'TXN-001'"
        ).fetchone()
        assert override["reason"] == "Actually a grocery run"
        assert override["vendor"] is None

        conn.close()


def test_override_without_reason_uses_default():
    """Override with no Notes column value should use 'Excel override' as reason."""
    with tempfile.TemporaryDirectory() as tmpdir:
        db_path, conn = _create_test_db(tmpdir)

        excel_path = _create_test_workbook(
            tmpdir,
            txn_id="TXN-001",
            tier1="Essential",
            tier2="Medical",
            reason=None,
        )

        count = read_overrides_from_excel(conn, excel_path)
        assert count == 1

        override = conn.execute(
            "SELECT vendor, reason FROM overrides WHERE transaction_id = 'TXN-001'"
        ).fetchone()
        assert override["reason"] == "Excel override"
        assert override["vendor"] is None

        conn.close()


def test_override_flag_not_set_skips_row():
    """Rows without Override=Y should not be processed."""
    with tempfile.TemporaryDirectory() as tmpdir:
        db_path, conn = _create_test_db(tmpdir)

        excel_path = _create_test_workbook(
            tmpdir,
            txn_id="TXN-001",
            tier1="Essential",
            tier2="Groceries",
            reason="Should not apply",
            override_flag="",
        )

        count = read_overrides_from_excel(conn, excel_path)
        assert count == 0

        txn = conn.execute(
            "SELECT tier1, tier2, vendor FROM transactions WHERE id = 'TXN-001'"
        ).fetchone()
        assert txn["tier1"] == "Non-Essential"
        assert txn["tier2"] == "Shopping"
        assert txn["vendor"] == "Some Store"

        conn.close()


if __name__ == "__main__":
    import pytest
    pytest.main([__file__, "-v"])
