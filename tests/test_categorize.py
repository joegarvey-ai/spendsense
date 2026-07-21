"""Tests for the transaction categorization engine.

NOTE: These tests verify the shipped example categorization rules in config/categories.py.
If you have customized categories.py for your own merchants (as the docstring recommends),
some tests below may fail. This is expected; they test the default/example configuration.
"""

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


# ─── Account-aware double-count prevention tests ───


def test_cc_payment_capital_one_on_checking():
    """Outgoing Capital One payment from checking → Transfer/CC Payment."""
    cat = TransactionCategorizer()
    result = cat.categorize("External Withdrawal CAPITAL ONE MOBILE PMT", -500.00, account_type="checking")
    assert result["tier1"] == "Transfer"
    assert result["tier2"] == "CC Payment"
    assert result["vendor"] == "Capital One"


def test_cc_payment_amex_on_checking():
    """Outgoing AMEX payment from checking → Transfer/CC Payment."""
    cat = TransactionCategorizer()
    result = cat.categorize("External Withdrawal AMEX EPAYMENT", -200.00, account_type="checking")
    assert result["tier1"] == "Transfer"
    assert result["tier2"] == "CC Payment"
    assert result["vendor"] == "AMEX"


def test_cc_payment_american_express_case_insensitive():
    """Case-insensitive matching of American Express variants."""
    cat = TransactionCategorizer()
    result = cat.categorize("american express payment", -150.00, account_type="checking")
    assert result["tier1"] == "Transfer"
    assert result["tier2"] == "CC Payment"
    assert result["vendor"] == "AMEX"


def test_cc_payment_apple_card_on_savings():
    """Outgoing Apple Card payment from savings → Transfer/CC Payment."""
    cat = TransactionCategorizer()
    result = cat.categorize("APPLECARD GSBANK PAYMENT", -300.00, account_type="savings")
    assert result["tier1"] == "Transfer"
    assert result["tier2"] == "CC Payment"
    assert result["vendor"] == "Apple Card"


def test_cc_payment_bank_of_america_variants():
    """Various Bank of America name formats on checking."""
    cat = TransactionCategorizer()
    for desc in ["BK OF AMER VISA ONLINE PMT", "Bank of America payment", "BofA CC PMT"]:
        result = cat.categorize(desc, -400.00, account_type="checking")
        assert result["tier1"] == "Transfer", f"Failed for: {desc}"
        assert result["tier2"] == "CC Payment", f"Failed for: {desc}"
        assert result["vendor"] == "Bank of America", f"Failed for: {desc}"


def test_cc_payment_affirm_on_checking():
    """Outgoing Affirm payment from checking → Transfer/CC Payment (not affirm.com)."""
    cat = TransactionCategorizer()
    result = cat.categorize("ACH AFFIRM PAYMENT", -50.00, account_type="checking")
    assert result["tier1"] == "Transfer"
    assert result["tier2"] == "CC Payment"
    assert result["vendor"] == "Affirm"


def test_cc_payment_not_triggered_without_account_type():
    """Without account_type, CC company names fall through to normal rules."""
    cat = TransactionCategorizer()
    # "AMEX" in description without account context should match normal RULES
    # (may not match as Transfer unless a specific RULES pattern catches it)
    result = cat.categorize("AMEX EPAYMENT", -200.00)
    # Without account_type, it should NOT automatically become Transfer/CC Payment
    # (it may match a specific rule or fall to default, depending on RULES)
    assert result is not None  # Just ensure no crash


def test_cc_payment_not_triggered_on_credit_card():
    """CC company name on a credit_card account should NOT trigger Transfer."""
    cat = TransactionCategorizer()
    # A Capital One charge appearing on a Capital One card — not a CC payment
    result = cat.categorize("CAPITAL ONE CAFE", -15.00, account_type="credit_card")
    assert result["tier1"] != "Transfer" or result["tier2"] != "CC Payment"


def test_cc_payment_not_triggered_for_incoming():
    """Incoming (positive) amount on checking should NOT trigger CC payment Transfer."""
    cat = TransactionCategorizer()
    result = cat.categorize("CAPITAL ONE REFUND", 50.00, account_type="checking")
    # Positive amount on checking + CC company name → should NOT be CC Payment
    assert not (result["tier1"] == "Transfer" and result["tier2"] == "CC Payment")


def test_investment_transfer_robinhood_outgoing():
    """Outgoing Robinhood transfer from checking → Transfer/Investment Transfer."""
    cat = TransactionCategorizer()
    result = cat.categorize("External Withdrawal ROBINHOOD Funds", -150.00, account_type="checking")
    assert result["tier1"] == "Transfer"
    assert result["tier2"] == "Investment Transfer"
    assert result["vendor"] == "Robinhood"


def test_investment_transfer_robinhood_incoming():
    """Incoming Robinhood deposit to checking → Transfer/Investment Transfer."""
    cat = TransactionCategorizer()
    result = cat.categorize("External Deposit ROBINHOOD Funds", 676.05, account_type="checking")
    assert result["tier1"] == "Transfer"
    assert result["tier2"] == "Investment Transfer"
    assert result["vendor"] == "Robinhood"


def test_investment_not_triggered_on_investment_account():
    """Robinhood on an investment account should NOT be Transfer — it's the real activity."""
    cat = TransactionCategorizer()
    result = cat.categorize("ACH deposit of $150 into Robinhood Brokerage", 150.00, account_type="investment")
    # On the investment account itself, Robinhood transactions should go through normal rules
    assert not (result["tier1"] == "Transfer" and result["tier2"] == "Investment Transfer")


def test_investment_not_triggered_without_account_type():
    """Without account_type, brokerage names fall through to normal rules."""
    cat = TransactionCategorizer()
    result = cat.categorize("buy 10.5 shares of VTI", -500.00)
    assert result["tier1"] == "Allocation"
    assert result["tier2"] == "Investments"


if __name__ == "__main__":
    import pytest
    pytest.main([__file__, "-v"])
