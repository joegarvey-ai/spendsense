"""Orchestrator: pull transactions from SimpleFIN → categorize → store → dedup."""

import logging
from datetime import datetime, timedelta, timezone
from decimal import Decimal

from config.accounts import get_account_type, get_friendly_name
from config.settings import SIMPLEFIN_BASE_URL, SIMPLEFIN_PASSWORD, SIMPLEFIN_USERNAME
from src.categorize import TransactionCategorizer
from src.db import (
    complete_sync_log,
    create_sync_log,
    get_connection,
    get_overrides,
    init_db,
    snapshot_balance,
    upsert_account,
    upsert_transaction,
)
from src.excel_writer import read_overrides_from_excel, update_dashboard
from src.simplefin_client import SimpleFINClient

logger = logging.getLogger(__name__)


def check_double_counts(conn, days_back: int = 90) -> list[dict]:
    """Scan for potential double-counted transactions.

    Finds transaction pairs where:
    - Same absolute amount (within $0.01)
    - Same or adjacent date (±3 days)
    - Different accounts
    - Both sides are NOT categorized as Transfer (i.e., both count toward spending)

    Pairs where one side is Transfer are expected (e.g., a bank-to-brokerage transfer
    where the bank side is Transfer/Investment Transfer and the brokerage side is
    Allocation/Investments). These are logged at DEBUG level for informational purposes.

    Args:
        conn: SQLite connection.
        days_back: How far back to scan (default 90 days).

    Returns:
        List of dicts describing critical double-counts (both sides non-Transfer).
    """
    cutoff = (datetime.now() - timedelta(days=days_back)).strftime("%Y-%m-%d")
    rows = conn.execute(
        """SELECT t1.id AS id1, t1.account_id AS acct1, t1.posted_at AS date1,
                  t1.amount AS amt1, t1.description AS desc1,
                  t1.tier1 AS tier1_1, t1.tier2 AS tier2_1,
                  a1.friendly_name AS name1,
                  t2.id AS id2, t2.account_id AS acct2, t2.posted_at AS date2,
                  t2.amount AS amt2, t2.description AS desc2,
                  t2.tier1 AS tier1_2, t2.tier2 AS tier2_2,
                  a2.friendly_name AS name2
           FROM transactions t1
           JOIN transactions t2 ON t1.id < t2.id
           LEFT JOIN accounts a1 ON t1.account_id = a1.id
           LEFT JOIN accounts a2 ON t2.account_id = a2.id
           WHERE ABS(ABS(t1.amount) - ABS(t2.amount)) < 0.01
             AND t1.account_id != t2.account_id
             AND ABS(julianday(t1.posted_at) - julianday(t2.posted_at)) <= 3
             AND (t1.tier1 != 'Transfer' OR t2.tier1 != 'Transfer')
             AND t1.posted_at >= ?
           ORDER BY t1.posted_at DESC""",
        (cutoff,),
    ).fetchall()

    critical = []  # Both sides non-Transfer = real double-count
    info = []      # One side Transfer, one not = expected (e.g., bank→brokerage)

    for r in rows:
        entry = {
            "date1": r["date1"], "amt1": r["amt1"], "desc1": r["desc1"],
            "cat1": f"{r['tier1_1']}/{r['tier2_1']}", "acct1": r["name1"] or r["acct1"],
            "date2": r["date2"], "amt2": r["amt2"], "desc2": r["desc2"],
            "cat2": f"{r['tier1_2']}/{r['tier2_2']}", "acct2": r["name2"] or r["acct2"],
            "id1": r["id1"], "id2": r["id2"],
        }
        if r["tier1_1"] != "Transfer" and r["tier1_2"] != "Transfer":
            critical.append(entry)
        else:
            info.append(entry)

    if critical:
        logger.warning(
            "DOUBLE-COUNT ALERT: %d transaction pair(s) where BOTH sides are spending (not Transfer):",
            len(critical),
        )
        for f in critical:
            logger.warning(
                "  %s $%.2f [%s] %s (%s) <-> %s $%.2f [%s] %s (%s)",
                f["date1"], f["amt1"], f["cat1"], f["desc1"][:40], f["acct1"],
                f["date2"], f["amt2"], f["cat2"], f["desc2"][:40], f["acct2"],
            )
    else:
        logger.info("Double-count check: CLEAN — no double-counted spending pairs found.")

    if info:
        logger.debug(
            "Double-count info: %d pair(s) with one Transfer side (expected, e.g. bank→brokerage).",
            len(info),
        )

    return critical


def run_daily_sync(days_back: int = 30, update_excel: bool = True) -> dict:
    """Run the full daily sync pipeline.

    1. Pull transactions from SimpleFIN (last N days)
    2. Dedup against existing DB records
    3. Categorize using rules engine (skip overrides)
    4. Upsert into SQLite
    5. Snapshot account balances
    6. Update Excel dashboard
    7. Post-sync double-count detection
    8. Log sync results

    Args:
        days_back: Number of days of history to fetch.
        update_excel: Whether to update the Excel dashboard after sync.

    Returns:
        Dict with sync results.
    """
    if not SIMPLEFIN_USERNAME or not SIMPLEFIN_PASSWORD:
        raise ValueError(
            "SimpleFIN credentials not configured. "
            "Run `python scripts/setup_simplefin.py` first, or set SIMPLEFIN_USERNAME "
            "and SIMPLEFIN_PASSWORD in .env"
        )

    # Initialize
    init_db()
    conn = get_connection()
    log_id = create_sync_log(conn, "daily")
    categorizer = TransactionCategorizer()
    overrides = get_overrides(conn)
    client = SimpleFINClient(SIMPLEFIN_USERNAME, SIMPLEFIN_PASSWORD, SIMPLEFIN_BASE_URL)

    errors = []
    fetched = 0
    new_count = 0
    updated_count = 0

    try:
        # Fetch transactions
        raw_transactions = client.get_all_transactions(days_back=days_back)
        fetched = len(raw_transactions)

        # Process accounts and snapshot balances
        accounts_meta = client.get_accounts_metadata(days_back=1)
        today = datetime.now().strftime("%Y-%m-%d")

        for acct in accounts_meta:
            upsert_account(conn, {
                "id": acct["id"],
                "institution": acct["institution"],
                "name": acct["name"],
                "friendly_name": get_friendly_name(acct["id"]),
                "account_type": get_account_type(acct["id"]),
                "currency": acct["currency"],
                "last_synced_at": datetime.now().isoformat(),
            })

            if acct["balance"] is not None:
                balance = float(Decimal(str(acct["balance"])))
                avail = (
                    float(Decimal(str(acct["available_balance"])))
                    if acct["available_balance"] is not None
                    else None
                )
                snapshot_balance(conn, acct["id"], balance, avail, today)

        # Build account_type lookup for double-count prevention
        account_type_map = {}
        for row in conn.execute("SELECT id, account_type FROM accounts").fetchall():
            account_type_map[row["id"]] = row["account_type"]

        # Process each transaction
        for raw_txn in raw_transactions:
            txn_id = raw_txn["id"]
            amount = float(Decimal(str(raw_txn["amount"])))
            posted_ts = raw_txn.get("posted")
            posted_date = (
                datetime.fromtimestamp(posted_ts, tz=timezone.utc).strftime("%Y-%m-%d")
                if posted_ts
                else today
            )
            month = posted_date[:7]  # YYYY-MM

            # Categorize (check overrides first)
            if txn_id in overrides:
                override = overrides[txn_id]
                category = {
                    "tier1": override["tier1"],
                    "tier2": override["tier2"],
                    "vendor": override.get("vendor"),
                }
                auto = 0
            else:
                acct_type = account_type_map.get(raw_txn["account_id"])
                category = categorizer.categorize(raw_txn["description"], amount, account_type=acct_type)
                auto = 1

            txn_record = {
                "id": txn_id,
                "account_id": raw_txn["account_id"],
                "posted_at": posted_date,
                "amount": amount,
                "description": raw_txn["description"],
                "pending": 1 if raw_txn.get("pending") else 0,
                "tier1": category["tier1"],
                "tier2": category["tier2"],
                "vendor": category["vendor"],
                "auto_categorized": auto,
                "month": month,
            }

            result = upsert_transaction(conn, txn_record)
            if result == "new":
                new_count += 1
            elif result == "updated":
                updated_count += 1

        conn.commit()

        # Read overrides from Excel (user may have edited Transaction Log)
        if update_excel:
            try:
                override_count = read_overrides_from_excel(conn)
                if override_count > 0:
                    logger.info("Applied %d overrides from Excel", override_count)
            except Exception as e:
                logger.warning("Failed to read Excel overrides: %s", e)

        # Update Excel dashboard + Transaction Log
        if update_excel:
            try:
                update_dashboard(conn)
                logger.info("Excel dashboard updated successfully")
            except Exception as e:
                errors.append(f"Excel update failed: {e}")
                logger.error("Failed to update Excel dashboard: %s", e)

        # ── Portfolio market data refresh (Phase 4) ──
        try:
            from src.brokerage_import import init_portfolio_schema
            init_portfolio_schema(conn)
            has_holdings = conn.execute("SELECT COUNT(*) FROM holdings").fetchone()[0]
            if has_holdings > 0:
                from src.market_data import MarketDataService
                from src.portfolio_analyzer import PortfolioAnalyzer
                market = MarketDataService(conn)
                market.refresh_holdings_prices()
                market.refresh_benchmarks(period="1mo")
                PortfolioAnalyzer(conn, market).snapshot_portfolio()
                logger.info("Portfolio prices and benchmarks refreshed")
        except Exception as e:
            logger.warning("Portfolio refresh skipped: %s", e)

        # Post-sync double-count detection
        double_counts = check_double_counts(conn, days_back=max(days_back, 90))
        if double_counts:
            errors.append(f"WARNING: {len(double_counts)} potential double-count(s) detected")

        # Log success
        complete_sync_log(conn, log_id, fetched, new_count, updated_count, errors or None, "success")
        logger.info(
            "Sync complete: %d fetched, %d new, %d updated",
            fetched, new_count, updated_count,
        )

    except Exception as e:
        errors.append(str(e))
        complete_sync_log(conn, log_id, fetched, new_count, updated_count, errors, "error")
        logger.error("Sync failed: %s", e)
        raise
    finally:
        conn.close()

    return {
        "fetched": fetched,
        "new": new_count,
        "updated": updated_count,
        "errors": errors,
    }
