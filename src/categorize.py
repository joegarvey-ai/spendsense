"""Transaction categorization engine using pattern matching rules."""
from __future__ import annotations

import logging
import re

from config.categories import DEFAULT_CATEGORY, RULES

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

    def categorize(self, description: str, amount: float = 0.0) -> dict:
        """Categorize a transaction by its description.

        Args:
            description: Raw merchant description from bank.
            amount: Transaction amount (negative=debit, positive=credit).

        Returns:
            Dict with keys: tier1, tier2, vendor.
        """
        for rule in self._compiled:
            if rule["regex"].search(description):
                tier1 = rule["tier1"]
                tier2 = rule["tier2"]
                vendor = rule["vendor"]

                # Check amount-based override (e.g., Venmo -$40 → Fixed/T-Mobile)
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
            "SELECT id, description, amount FROM transactions WHERE auto_categorized = 1"
        ).fetchall()

        updated = 0
        skipped = 0

        for row in rows:
            if row["id"] in overrides:
                skipped += 1
                continue

            result = self.categorize(row["description"], row["amount"])
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
