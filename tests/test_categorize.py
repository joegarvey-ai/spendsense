"""Tests for the transaction categorization engine."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from src.categorize import TransactionCategorizer


def test_groceries():
    cat = TransactionCategorizer()
    result = cat.categorize("FRED MEYER #1234", -52.34)
    assert result["tier1"] == "Essential"
    assert result["tier2"] == "Groceries"


def test_costco_groceries():
    cat = TransactionCategorizer()
    result = cat.categorize("COSTCO WHSE #1234", -150.00)
    assert result["tier1"] == "Essential"
    assert result["tier2"] == "Groceries"
    assert result["vendor"] == "Costco"


def test_costco_gas():
    cat = TransactionCategorizer()
    result = cat.categorize("COSTCO GAS #1234", -45.00)
    assert result["tier1"] == "Essential"
    assert result["tier2"] == "Auto — Fuel"
    assert result["vendor"] == "Costco Gas"


def test_amazon():
    cat = TransactionCategorizer()
    result = cat.categorize("AMZN Mktp US*AB1CD2EF3", -29.99)
    assert result["tier1"] == "Non-Essential"
    assert result["tier2"] == "Amazon"
    assert result["vendor"] == "Amazon"


def test_starbucks():
    cat = TransactionCategorizer()
    result = cat.categorize("STARBUCKS STORE 12345", -6.75)
    assert result["tier1"] == "Non-Essential"
    assert result["tier2"] == "Dining Out"
    assert result["vendor"] == "Starbucks"


def test_subscription():
    cat = TransactionCategorizer()
    result = cat.categorize("NETFLIX.COM", -15.99)
    assert result["tier1"] == "Non-Essential"
    assert result["tier2"] == "Subscriptions"


def test_xfinity():
    cat = TransactionCategorizer()
    result = cat.categorize("COMCAST CABLE COMM", -89.99)
    assert result["tier1"] == "Fixed"
    assert result["tier2"] == "Internet"


def test_doordash():
    cat = TransactionCategorizer()
    result = cat.categorize("DOORDASH*ORDER 12345", -32.50)
    assert result["tier1"] == "Non-Essential"
    assert result["tier2"] == "Food Delivery"
    assert result["vendor"] == "DoorDash"


def test_savings_transfer():
    cat = TransactionCategorizer()
    result = cat.categorize("TRANSFER TO SAV 1234", -500.00)
    assert result["tier1"] == "Allocation"
    assert result["tier2"] == "Savings"


def test_uncategorized():
    cat = TransactionCategorizer()
    result = cat.categorize("RANDOM STORE XYZ 999", -20.00)
    assert result["tier1"] == "Non-Essential"
    assert result["tier2"] == "Misc / Uncategorized"


def test_case_insensitive():
    cat = TransactionCategorizer()
    result = cat.categorize("fred meyer #5678", -45.00)
    assert result["tier1"] == "Essential"
    assert result["tier2"] == "Groceries"


def test_anthropic():
    cat = TransactionCategorizer()
    result = cat.categorize("ANTHROPIC INC", -20.00)
    assert result["tier1"] == "Fixed"
    assert result["tier2"] == "AI Tools"
    assert result["vendor"] == "Anthropic"


if __name__ == "__main__":
    import pytest
    pytest.main([__file__, "-v"])
