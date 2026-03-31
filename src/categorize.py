"""Transaction categorization engine using pattern matching rules."""
from __future__ import annotations

import logging
import re

from config.categories import (
    CC_COMPANY_PATTERNS,
    DEFAULT_CATEGORY,
    INVESTMENT_COMPANY_PATTERNS,
    RULES,
)

logger = logging.getLogger(__name__)


class TransactionCategorizer:
    """Categorizes transactions by matching description against ordered rules."""

    def __init__(self, rules: list[dict] = None):
        self.rules = rules or RULES
        # Pre-compile regex patterns at init for performance
        self._compiled = []
        for rule in self.rules:
            self._compiled.append({
                "regex": re.compile(rule["pattern"], re.IGNORECASE),
                "tier1": rule["tier1"],
                "tier2": rule["tier2"],
                "vendor": rule["vendor"],
                "amount_match": rule.get("amount_match"),
            })

        # Pre-compile CC and investment company patterns for double-count prevention
        self._cc_patterns = [
            {"regex": re.compile(p["pattern"], re.IGNORECASE), "vendor": p["vendor"]}
            for p in CC_COMPANY_PATTERNS
        ]
        self._investment_patterns = [
            {"regex": re.compile(p["pattern"], re.IGNORECASE), "vendor": p["vendor"]}
            for p in INVESTMENT_COMPANY_PATTERNS
        ]

    def categorize(self, description: str, amount: float = 0.0, account_type: str = None) -> dict:
        """Categorize a transaction by its description.

        Args:
            description: Raw merchant description from bank.
            amount: Transaction amount (negative=debit, positive=credit).
            account_type: Account type (checking, savings, credit_card, investment, etc.).
                When provided, enables account-aware double-count prevention:
                bank accounts with CC company names → Transfer/CC Payment,
                bank accounts with brokerage names → Transfer/Investment Transfer.

        Returns:
            Dict with keys: tier1, tier2, vendor.
        """
        # Double-count prevention: detect inter-account transfers by account context
        if account_type:
            transfer = self._check_transfer_pattern(description, amount, account_type)
            if transfer:
                return transfer

        for rule in self._compiled:
            if rule["regex"].search(description):
                tier1 = rule["tier1"]
                tier2 = rule["tier2"]
                vendor = rule["vendor"]

                # Check amount-based override (e.g., Venmo -$40 → Fixed/Cell Phone)
                am = rule["amount_match"]
                if am and "exact" in am and amount == am["exact"]:
                    tier1 = am["override_tier1"]
                    tier2 = am["override_tier2"]

                if vendor is None:
                    vendor = self._clean_vendor(description)
                return {
                    "tier1": tier1,
                    "tier2": tier2,
                    "vendor": vendor,
                }

        # No match — fall through to default
        return {
            "tier1": DEFAULT_CATEGORY["tier1"],
            "tier2": DEFAULT_CATEGORY["tier2"],
            "vendor": self._clean_vendor(description),
        }

    def recategorize_all(self, conn) -> dict:
        """Re-run rules on all auto-categorized transactions (skip overrides).

        Returns:
            Dict with counts: {'updated': N, 'skipped': N}.
        """
        from src.db import get_overrides

        overrides = get_overrides(conn)
        rows = conn.execute(
            """SELECT t.id, t.description, t.amount, t.account_id, a.account_type
               FROM transactions t
               LEFT JOIN accounts a ON t.account_id = a.id
               WHERE t.auto_categorized = 1"""
        ).fetchall()

        updated = 0
        skipped = 0

        for row in rows:
            if row["id"] in overrides:
                skipped += 1
                continue

            result = self.categorize(row["description"], row["amount"], row["account_type"])
            conn.execute(
                """UPDATE transactions SET
                       tier1 = ?, tier2 = ?, vendor = ?,
                       updated_at = datetime('now')
                   WHERE id = ?""",
                (result["tier1"], result["tier2"], result["vendor"], row["id"]),
            )
            updated += 1

        conn.commit()
        logger.info("Recategorized %d transactions (%d skipped as overrides)", updated, skipped)
        return {"updated": updated, "skipped": skipped}

    def _check_transfer_pattern(self, description: str, amount: float, account_type: str) -> dict | None:
        """Detect inter-account transfers to prevent double-counting.

        This runs BEFORE the normal RULES matching. It catches cases where a bank
        account shows a transaction to/from a credit card company or brokerage,
        which should always be Transfer — not spending or allocation.

        Rules applied:
        - Bank account + CC company name + outgoing (negative) → Transfer/CC Payment
        - Bank account + investment company name → Transfer/Investment Transfer
        """
        is_bank = account_type in ("checking", "savings")

        # CC payments: bank-side outgoing to a credit card company
        if is_bank and amount < 0:
            for pat in self._cc_patterns:
                if pat["regex"].search(description):
                    return {"tier1": "Transfer", "tier2": "CC Payment", "vendor": pat["vendor"]}

        # Investment transfers: any bank-side transaction involving an investment company
        if is_bank:
            for pat in self._investment_patterns:
                if pat["regex"].search(description):
                    return {"tier1": "Transfer", "tier2": "Investment Transfer", "vendor": pat["vendor"]}

        return None

    @staticmethod
    def _clean_vendor(description: str) -> str:
        """Clean up a raw transaction description into a readable vendor name."""
        # Remove common suffixes like location codes, card numbers, dates
        cleaned = re.sub(r"\s*#\d+.*$", "", description)
        cleaned = re.sub(r"\s+\d{2}/\d{2}.*$", "", cleaned)
        cleaned = re.sub(r"\s+[A-Z]{2}\s*$", "", cleaned)  # State abbreviations
        cleaned = re.sub(r"\s{2,}", " ", cleaned).strip()
        # Title case
        if cleaned.isupper():
            cleaned = cleaned.title()
        return cleaned[:50]  # Cap length
