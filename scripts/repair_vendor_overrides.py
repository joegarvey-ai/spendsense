"""One-time repair script: fix vendor column corruption from the apply_override keyword bug.

The bug: excel_writer.py passed the override reason as a positional argument to
apply_override(), which bound it to the vendor parameter. This overwrote
transactions.vendor with user notes (or "Excel override") and stored reason=NULL.

This script:
1. Finds all overrides where vendor looks like it was set by the bug
2. Re-categorizes the original transaction description to recover the correct vendor
3. Clears the corrupted vendor from overrides (sets to NULL)
4. Updates transactions.vendor to the re-categorized value

Safe to run multiple times (idempotent).
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

try:
    from config.settings import DB_PATH
except ImportError:
    print("Error: config/settings.py not found.")
    print("Copy config/settings.example.py to config/settings.py and fill in your values.")
    sys.exit(1)

from src.categorize import TransactionCategorizer
from src.db import get_connection, init_db


def main():
    if not DB_PATH.exists():
        print(f"Database not found at {DB_PATH}. Nothing to repair.")
        sys.exit(0)

    conn = get_connection()
    categorizer = TransactionCategorizer()

    overrides = conn.execute(
        "SELECT transaction_id, tier1, tier2, vendor, reason FROM overrides"
    ).fetchall()

    if not overrides:
        print("No overrides found. Nothing to repair.")
        conn.close()
        return

    repaired = 0
    skipped = 0

    for ov in overrides:
        txn_id = ov["transaction_id"]
        ov_vendor = ov["vendor"]
        ov_reason = ov["reason"]

        if ov_vendor is None and ov_reason is not None:
            skipped += 1
            continue

        txn = conn.execute(
            "SELECT description, amount, account_id FROM transactions WHERE id = ?",
            (txn_id,),
        ).fetchone()

        if not txn:
            skipped += 1
            continue

        acct_row = conn.execute(
            "SELECT account_type FROM accounts WHERE id = ?",
            (txn["account_id"],),
        ).fetchone()
        account_type = acct_row["account_type"] if acct_row else None

        correct_category = categorizer.categorize(
            txn["description"], txn["amount"], account_type=account_type
        )
        correct_vendor = correct_category["vendor"]

        conn.execute(
            "UPDATE overrides SET vendor = NULL, reason = ? WHERE transaction_id = ?",
            (ov_vendor if ov_vendor else None, txn_id),
        )

        conn.execute(
            "UPDATE transactions SET vendor = ?, updated_at = datetime('now') WHERE id = ?",
            (correct_vendor, txn_id),
        )
        repaired += 1

    conn.commit()
    conn.close()

    print(f"Repair complete: {repaired} overrides fixed, {skipped} skipped (already correct).")
    if repaired > 0:
        print("Vendor values restored from re-categorization. Old vendor values moved to reason column where reason was NULL.")


if __name__ == "__main__":
    main()
