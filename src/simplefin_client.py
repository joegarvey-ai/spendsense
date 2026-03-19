"""SimpleFIN API wrapper for fetching account and transaction data."""
from __future__ import annotations

import logging
from datetime import datetime, timedelta

import requests

logger = logging.getLogger(__name__)


class SimpleFINClient:
    """Client for the SimpleFIN Bridge API."""

    def __init__(self, username: str, password: str, base_url: str):
        self.username = username
        self.password = password
        self.base_url = base_url.rstrip("/")
        self.session = requests.Session()
        self.session.auth = (username, password)

    def get_accounts(
        self,
        start_date: datetime = None,
        end_date: datetime = None,
        account_id: str = None,
    ) -> dict:
        """Fetch accounts and transactions. Returns raw JSON response.

        Args:
            start_date: Filter transactions from this date (inclusive).
            end_date: Filter transactions to this date (inclusive).
            account_id: Fetch only this account's data.

        Returns:
            Dict with 'errors' and 'accounts' keys.
        """
        url = f"{self.base_url}/accounts"
        params = {}

        if start_date:
            params["start-date"] = int(start_date.timestamp())
        if end_date:
            params["end-date"] = int(end_date.timestamp())
        if account_id:
            params["account"] = account_id

        logger.info("Fetching SimpleFIN accounts: %s params=%s", url, params)

        response = self.session.get(url, params=params, timeout=30)
        response.raise_for_status()
        data = response.json()

        # Check for API errors
        if data.get("errors"):
            for error in data["errors"]:
                logger.warning("SimpleFIN API error: %s", error)

        return data

    def get_all_transactions(self, days_back: int = 30) -> list[dict]:
        """Fetch all accounts, flatten transactions, attach account metadata.

        Args:
            days_back: How many days of history to fetch (max 90).

        Returns:
            List of transaction dicts, each enriched with account info.
        """
        days_back = min(days_back, 90)  # SimpleFIN limit
        start_date = datetime.now() - timedelta(days=days_back)

        data = self.get_accounts(start_date=start_date)
        transactions = []

        for account in data.get("accounts", []):
            account_info = {
                "account_id": account["id"],
                "institution": account.get("org", {}).get("name", "Unknown"),
                "account_name": account.get("name", "Unknown"),
                "currency": account.get("currency", "USD"),
                "balance": account.get("balance"),
                "available_balance": account.get("available-balance"),
                "balance_date": account.get("balance-date"),
            }

            for txn in account.get("transactions", []):
                enriched = {
                    **account_info,
                    "id": f"{account['id']}:{txn['id']}",
                    "raw_txn_id": txn["id"],
                    "posted": txn.get("posted"),
                    "amount": txn.get("amount", "0"),
                    "description": txn.get("description", ""),
                    "pending": txn.get("pending", False),
                }
                transactions.append(enriched)

        logger.info(
            "Fetched %d transactions across %d accounts",
            len(transactions),
            len(data.get("accounts", [])),
        )
        return transactions

    def get_accounts_metadata(self, days_back: int = 1) -> list[dict]:
        """Fetch account metadata (balances, names) without full transaction history."""
        start_date = datetime.now() - timedelta(days=days_back)
        data = self.get_accounts(start_date=start_date)

        accounts = []
        for account in data.get("accounts", []):
            accounts.append({
                "id": account["id"],
                "institution": account.get("org", {}).get("name", "Unknown"),
                "name": account.get("name", "Unknown"),
                "currency": account.get("currency", "USD"),
                "balance": account.get("balance"),
                "available_balance": account.get("available-balance"),
                "balance_date": account.get("balance-date"),
            })
        return accounts
