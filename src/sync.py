"""Orchestrator: pull transactions from SimpleFIN → categorize → store → dedup."""

import logging
from datetime import datetime, timezone
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


def run_daily_sync(days_back: int = 30, update_excel: bool = True) -> dict:
    """Run the full daily sync pipeline.

    1. Pull transactions from SimpleFIN (last N days)
    2. Dedup against existing DB records
    3. Categorize using rules engine (skip overrides)
    4. Upsert into SQLite
    5. Snapshot account balances
    6. Update Excel dashboard
    7. Log sync results

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
                category = categorizer.categorize(raw_txn["description"], amount)
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
