"""Brokerage CSV importer and dividend-based fallback for building holdings table.

Supports common brokerage CSV export formats (tested with Robinhood, Schwab, Fidelity).
Looks for standard column names like Symbol/Ticker, Quantity/Shares, Average Cost, etc.
"""

from __future__ import annotations

import csv
import logging
import re
import sqlite3
from datetime import datetime
from pathlib import Path

logger = logging.getLogger(__name__)

# ── Portfolio schema (extends existing DB) ──
PORTFOLIO_SCHEMA = """
CREATE TABLE IF NOT EXISTS holdings (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ticker TEXT NOT NULL,
    account TEXT NOT NULL,
    shares REAL NOT NULL,
    avg_cost_basis REAL NOT NULL,
    total_cost REAL,
    estimated INTEGER DEFAULT 0,
    notes TEXT,
    last_updated TEXT,
    UNIQUE(ticker, account)
);

CREATE TABLE IF NOT EXISTS market_data (
    ticker TEXT PRIMARY KEY,
    name TEXT,
    sector TEXT,
    industry TEXT,
    current_price REAL,
    day_change_pct REAL,
    market_cap REAL,
    pe_ratio REAL,
    dividend_yield REAL,
    beta REAL,
    fifty_two_week_high REAL,
    fifty_two_week_low REAL,
    last_fetched TEXT
);

CREATE TABLE IF NOT EXISTS portfolio_snapshots (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    snapshot_date TEXT NOT NULL,
    account TEXT NOT NULL,
    total_value REAL NOT NULL,
    total_cost_basis REAL NOT NULL,
    total_gain_loss REAL NOT NULL,
    gain_loss_pct REAL NOT NULL,
    UNIQUE(snapshot_date, account)
);

CREATE TABLE IF NOT EXISTS benchmark_data (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ticker TEXT NOT NULL,
    date TEXT NOT NULL,
    close_price REAL NOT NULL,
    UNIQUE(ticker, date)
);
"""


def init_portfolio_schema(conn: sqlite3.Connection) -> None:
    """Create portfolio-related tables."""
    conn.executescript(PORTFOLIO_SCHEMA)
    conn.commit()
    logger.info("Portfolio schema initialized")


def import_brokerage_csv(conn: sqlite3.Connection, csv_path: str | Path) -> dict:
    """Import holdings from a brokerage CSV export.

    Supports common CSV formats from major brokerages. Looks for columns
    like Instrument/Symbol, Quantity, Average Cost, etc.

    Returns: {"imported": N, "skipped": N, "errors": []}
    """
    init_portfolio_schema(conn)
    csv_path = Path(csv_path)
    if not csv_path.exists():
        raise FileNotFoundError(f"CSV not found: {csv_path}")

    imported = 0
    skipped = 0
    errors = []

    with open(csv_path, newline="", encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        headers = reader.fieldnames or []
        logger.info("CSV headers: %s", headers)

        # Map common brokerage column names
        ticker_col = _find_col(headers, ["Symbol", "Ticker", "Instrument"])
        qty_col = _find_col(headers, ["Quantity", "Shares", "Qty"])
        cost_col = _find_col(headers, ["Average Cost", "Avg Cost", "Cost Basis", "Average Price"])
        account_col = _find_col(headers, ["Account", "Account Type", "Account Name"])

        if not ticker_col or not qty_col:
            raise ValueError(f"Cannot find ticker/quantity columns in: {headers}")

        for row in reader:
            ticker = (row.get(ticker_col) or "").strip().upper()
            if not ticker or ticker in ("", "N/A"):
                skipped += 1
                continue

            try:
                shares = float(row.get(qty_col, "0").replace(",", ""))
                avg_cost = float(row.get(cost_col, "0").replace(",", "").replace("$", "")) if cost_col else 0.0
                account = row.get(account_col, "Individual").strip() if account_col else "Individual"
            except (ValueError, TypeError) as e:
                errors.append(f"Bad data for {ticker}: {e}")
                continue

            if shares <= 0:
                skipped += 1
                continue

            conn.execute(
                """INSERT INTO holdings (ticker, account, shares, avg_cost_basis, total_cost, estimated, last_updated)
                   VALUES (?, ?, ?, ?, ?, 0, ?)
                   ON CONFLICT(ticker, account) DO UPDATE SET
                       shares = excluded.shares,
                       avg_cost_basis = excluded.avg_cost_basis,
                       total_cost = excluded.total_cost,
                       estimated = 0,
                       last_updated = excluded.last_updated""",
                (ticker, account, shares, avg_cost, shares * avg_cost, datetime.now().isoformat()),
            )
            imported += 1

    conn.commit()
    logger.info("Brokerage CSV import: %d imported, %d skipped, %d errors", imported, skipped, len(errors))
    return {"imported": imported, "skipped": skipped, "errors": errors}


def build_holdings_from_dividends(conn: sqlite3.Connection, tickers: list[str]) -> dict:
    """Fallback: create preliminary holdings from dividend transaction history.

    Since we don't have share counts, we set shares=0 and flag as estimated.
    The user must manually update share counts later or import a CSV.

    Returns: {"created": N, "already_exists": N}
    """
    init_portfolio_schema(conn)
    created = 0
    already_exists = 0

    for ticker in tickers:
        existing = conn.execute(
            "SELECT id FROM holdings WHERE ticker = ?", (ticker,)
        ).fetchone()

        if existing:
            already_exists += 1
            continue

        # Check which brokerage account paid dividends for this ticker
        div_row = conn.execute(
            """SELECT account_id, COUNT(*) as cnt, SUM(amount) as total_divs
               FROM transactions
               WHERE description LIKE ? AND tier2 = 'Dividends'
               GROUP BY account_id
               ORDER BY cnt DESC LIMIT 1""",
            (f"%{ticker}%",),
        ).fetchone()

        # Try to determine account from the SimpleFIN account_id
        from config.portfolio_config import BROKERAGE_ACCOUNTS
        account = "Individual"  # Default
        if div_row and div_row["account_id"] in BROKERAGE_ACCOUNTS:
            account = BROKERAGE_ACCOUNTS[div_row["account_id"]]

        conn.execute(
            """INSERT INTO holdings (ticker, account, shares, avg_cost_basis, total_cost, estimated, notes, last_updated)
               VALUES (?, ?, 0, 0, 0, 1, ?, ?)""",
            (
                ticker,
                account,
                "Estimated from dividend history — update shares and cost basis manually or via CSV import",
                datetime.now().isoformat(),
            ),
        )
        created += 1

    conn.commit()
    logger.info("Dividend fallback: %d created, %d already existed", created, already_exists)
    return {"created": created, "already_exists": already_exists}


def _find_col(headers: list[str], candidates: list[str]) -> str | None:
    """Find first matching column header (case-insensitive)."""
    lower_headers = {h.lower().strip(): h for h in headers}
    for c in candidates:
        if c.lower() in lower_headers:
            return lower_headers[c.lower()]
    return None
