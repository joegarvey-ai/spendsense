"""SQLite schema and CRUD operations for the SpendSense database."""
from __future__ import annotations

import json
import sqlite3
from datetime import datetime
from pathlib import Path

from config.loader import settings

SCHEMA = """
-- Accounts linked via SimpleFIN
CREATE TABLE IF NOT EXISTS accounts (
    id TEXT PRIMARY KEY,
    institution TEXT NOT NULL,
    name TEXT NOT NULL,
    friendly_name TEXT,
    account_type TEXT,
    currency TEXT DEFAULT 'USD',
    last_synced_at TEXT,
    created_at TEXT DEFAULT (datetime('now'))
);

-- All transactions
CREATE TABLE IF NOT EXISTS transactions (
    id TEXT PRIMARY KEY,
    account_id TEXT NOT NULL REFERENCES accounts(id),
    posted_at TEXT NOT NULL,
    amount REAL NOT NULL,
    description TEXT NOT NULL,
    pending INTEGER DEFAULT 0,
    tier1 TEXT,
    tier2 TEXT,
    vendor TEXT,
    auto_categorized INTEGER DEFAULT 1,
    month TEXT,
    created_at TEXT DEFAULT (datetime('now')),
    updated_at TEXT DEFAULT (datetime('now'))
);

-- Manual category overrides (survives re-categorization)
CREATE TABLE IF NOT EXISTS overrides (
    transaction_id TEXT PRIMARY KEY REFERENCES transactions(id),
    tier1 TEXT NOT NULL,
    tier2 TEXT NOT NULL,
    vendor TEXT,
    reason TEXT,
    created_at TEXT DEFAULT (datetime('now'))
);

-- Monthly budget targets
CREATE TABLE IF NOT EXISTS budgets (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    month TEXT NOT NULL,
    tier1 TEXT NOT NULL,
    tier2 TEXT NOT NULL,
    budget_amount REAL NOT NULL,
    UNIQUE(month, tier1, tier2)
);

-- Account balances snapshot (daily)
CREATE TABLE IF NOT EXISTS balance_snapshots (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    account_id TEXT NOT NULL REFERENCES accounts(id),
    balance REAL NOT NULL,
    available_balance REAL,
    snapshot_date TEXT NOT NULL,
    created_at TEXT DEFAULT (datetime('now')),
    UNIQUE(account_id, snapshot_date)
);

-- Sync log for debugging
CREATE TABLE IF NOT EXISTS sync_log (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    sync_type TEXT NOT NULL,
    started_at TEXT NOT NULL,
    completed_at TEXT,
    transactions_fetched INTEGER DEFAULT 0,
    transactions_new INTEGER DEFAULT 0,
    transactions_updated INTEGER DEFAULT 0,
    errors TEXT,
    status TEXT DEFAULT 'running'
);

CREATE INDEX IF NOT EXISTS idx_transactions_month ON transactions(month);
CREATE INDEX IF NOT EXISTS idx_transactions_account ON transactions(account_id);
CREATE INDEX IF NOT EXISTS idx_transactions_tier1 ON transactions(tier1);
CREATE INDEX IF NOT EXISTS idx_transactions_posted ON transactions(posted_at);
CREATE INDEX IF NOT EXISTS idx_balance_date ON balance_snapshots(snapshot_date);
"""


def get_connection(db_path: Path = None) -> sqlite3.Connection:
    """Get a SQLite connection with row factory enabled."""
    path = db_path or settings.DB_PATH
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        path.parent.chmod(0o700)
    except OSError:
        pass
    conn = sqlite3.connect(str(path))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


def init_db(db_path: Path = None) -> None:
    """Create all tables and indexes."""
    conn = get_connection(db_path)
    conn.executescript(SCHEMA)
    conn.close()


def upsert_account(conn: sqlite3.Connection, account: dict) -> None:
    """Insert or update an account record."""
    conn.execute(
        """INSERT INTO accounts (id, institution, name, friendly_name, account_type, currency, last_synced_at)
           VALUES (:id, :institution, :name, :friendly_name, :account_type, :currency, :last_synced_at)
           ON CONFLICT(id) DO UPDATE SET
               institution = excluded.institution,
               name = excluded.name,
               friendly_name = COALESCE(accounts.friendly_name, excluded.friendly_name),
               account_type = COALESCE(accounts.account_type, excluded.account_type),
               currency = excluded.currency,
               last_synced_at = excluded.last_synced_at""",
        account,
    )
    conn.commit()


def upsert_transaction(conn: sqlite3.Connection, txn: dict) -> str:
    """Insert or update a transaction. Returns 'new', 'updated', or 'skipped'."""
    existing = conn.execute(
        "SELECT id, pending, amount, description FROM transactions WHERE id = ?",
        (txn["id"],),
    ).fetchone()

    if existing is None:
        conn.execute(
            """INSERT INTO transactions
               (id, account_id, posted_at, amount, description, pending,
                tier1, tier2, vendor, auto_categorized, month)
               VALUES (:id, :account_id, :posted_at, :amount, :description, :pending,
                       :tier1, :tier2, :vendor, :auto_categorized, :month)""",
            txn,
        )
        return "new"

    # Check if anything changed (e.g. pending→posted)
    changed = (
        existing["pending"] != txn["pending"]
        or existing["amount"] != txn["amount"]
        or existing["description"] != txn["description"]
    )
    if changed:
        conn.execute(
            """UPDATE transactions SET
                   pending = :pending,
                   amount = :amount,
                   description = :description,
                   posted_at = :posted_at,
                   updated_at = datetime('now')
               WHERE id = :id""",
            txn,
        )
        return "updated"

    return "skipped"


def snapshot_balance(
    conn: sqlite3.Connection,
    account_id: str,
    balance: float,
    available_balance: float | None,
    snapshot_date: str,
) -> None:
    """Record a daily balance snapshot."""
    conn.execute(
        """INSERT INTO balance_snapshots (account_id, balance, available_balance, snapshot_date)
           VALUES (?, ?, ?, ?)
           ON CONFLICT(account_id, snapshot_date) DO UPDATE SET
               balance = excluded.balance,
               available_balance = excluded.available_balance""",
        (account_id, balance, available_balance, snapshot_date),
    )
    conn.commit()


def get_monthly_summary(conn: sqlite3.Connection, month: str) -> list[dict]:
    """Get aggregated totals by tier1/tier2 for a given month (YYYY-MM)."""
    rows = conn.execute(
        """SELECT tier1, tier2, vendor,
                  SUM(amount) as total,
                  COUNT(*) as count
           FROM transactions
           WHERE month = ? AND pending = 0
           GROUP BY tier1, tier2
           ORDER BY tier1, tier2""",
        (month,),
    ).fetchall()
    return [dict(r) for r in rows]


def get_uncategorized(conn: sqlite3.Connection) -> list[dict]:
    """Get transactions with no category assigned or in Misc/Uncategorized."""
    rows = conn.execute(
        """SELECT id, account_id, posted_at, amount, description, month
           FROM transactions
           WHERE tier1 IS NULL
              OR tier2 = 'Misc / Uncategorized'
           ORDER BY posted_at DESC""",
    ).fetchall()
    return [dict(r) for r in rows]


def apply_override(
    conn: sqlite3.Connection,
    txn_id: str,
    tier1: str,
    tier2: str,
    *,
    vendor: str | None = None,
    reason: str | None = None,
) -> None:
    """Apply a manual category override to a transaction."""
    conn.execute(
        """INSERT INTO overrides (transaction_id, tier1, tier2, vendor, reason)
           VALUES (?, ?, ?, ?, ?)
           ON CONFLICT(transaction_id) DO UPDATE SET
               tier1 = excluded.tier1,
               tier2 = excluded.tier2,
               vendor = excluded.vendor,
               reason = excluded.reason""",
        (txn_id, tier1, tier2, vendor, reason),
    )
    conn.execute(
        """UPDATE transactions SET
               tier1 = ?, tier2 = ?, vendor = ?,
               auto_categorized = 0, updated_at = datetime('now')
           WHERE id = ?""",
        (tier1, tier2, vendor, txn_id),
    )
    conn.commit()


def get_overrides(conn: sqlite3.Connection) -> dict[str, dict]:
    """Return all overrides keyed by transaction_id."""
    rows = conn.execute("SELECT * FROM overrides").fetchall()
    return {r["transaction_id"]: dict(r) for r in rows}


def get_balance_history(
    conn: sqlite3.Connection, account_id: str, days: int = 90
) -> list[dict]:
    """Get balance snapshots for an account over the last N days."""
    rows = conn.execute(
        """SELECT snapshot_date, balance, available_balance
           FROM balance_snapshots
           WHERE account_id = ?
           ORDER BY snapshot_date DESC
           LIMIT ?""",
        (account_id, days),
    ).fetchall()
    return [dict(r) for r in rows]


def get_all_accounts(conn: sqlite3.Connection) -> list[dict]:
    """Return all accounts."""
    rows = conn.execute("SELECT * FROM accounts ORDER BY institution, name").fetchall()
    return [dict(r) for r in rows]


def create_sync_log(conn: sqlite3.Connection, sync_type: str) -> int:
    """Create a new sync log entry. Returns the log ID."""
    cursor = conn.execute(
        "INSERT INTO sync_log (sync_type, started_at) VALUES (?, ?)",
        (sync_type, datetime.now().isoformat()),
    )
    conn.commit()
    return cursor.lastrowid


def complete_sync_log(
    conn: sqlite3.Connection,
    log_id: int,
    fetched: int,
    new: int,
    updated: int,
    errors: list[str] | None = None,
    status: str = "success",
) -> None:
    """Mark a sync log entry as complete."""
    conn.execute(
        """UPDATE sync_log SET
               completed_at = ?,
               transactions_fetched = ?,
               transactions_new = ?,
               transactions_updated = ?,
               errors = ?,
               status = ?
           WHERE id = ?""",
        (
            datetime.now().isoformat(),
            fetched,
            new,
            updated,
            json.dumps(errors) if errors else None,
            status,
            log_id,
        ),
    )
    conn.commit()


def get_last_sync(conn: sqlite3.Connection) -> dict | None:
    """Return the most recent sync log entry."""
    row = conn.execute(
        "SELECT * FROM sync_log ORDER BY id DESC LIMIT 1"
    ).fetchone()
    return dict(row) if row else None


def get_transaction_count(conn: sqlite3.Connection) -> int:
    """Return total number of transactions."""
    return conn.execute("SELECT COUNT(*) FROM transactions").fetchone()[0]
