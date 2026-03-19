"""Portfolio and strategy configuration — copy to portfolio_config.py and fill in your values."""

# ── Debt parameters (update with your actual loan details) ──
MORTGAGE_RATE = 0.04           # APR as decimal (e.g., 4.0%)
MORTGAGE_BALANCE = 400000      # Approximate remaining balance
MORTGAGE_MONTHLY = 2500        # Monthly payment (P&I)
MORTGAGE_TERM_REMAINING = 300  # Approximate months remaining

CAR_LOAN_RATE = 0.055          # APR as decimal (e.g., 5.5%)
CAR_BALANCE = 25000            # Remaining balance
CAR_MONTHLY = 500              # Monthly payment
CAR_TERM_REMAINING = 48        # Months remaining

# ── IRA ──
IRA_ANNUAL_LIMIT = 7000        # 2026 contribution limit (verify annually)
IRA_ACCOUNT = "Traditional IRA"

# ── Investment assumptions ──
ASSUMED_MARKET_RETURN = 0.10   # 10% long-term average annual return
RISK_FREE_RATE = 0.043         # ~4.3% (approximate 10Y Treasury yield)

# ── Benchmark tickers ──
BENCHMARKS = {
    "S&P 500": "^GSPC",
    "Nasdaq": "^IXIC",
    "Dow Jones": "^DJI",
    "10Y Treasury": "^TNX",
    "VIX": "^VIX",
}

# ── Brokerage accounts ──
# Map SimpleFIN account IDs to friendly names for your investment accounts.
# Run `python -m src.cli status` after first sync to discover account IDs.
BROKERAGE_ACCOUNTS = {
    # "ACT-xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx": "Individual (1234)",
    # "ACT-xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx": "Traditional IRA (5678)",
}

# ── Known tickers ──
# Pre-populate from your dividend history or brokerage statements.
# Used by the dividend-based fallback when CSV import isn't available.
KNOWN_TICKERS = [
    # "AAPL", "MSFT", "GOOGL", "VTI", "SPY",
]

# ── Concentration risk threshold ──
CONCENTRATION_WARN_PCT = 0.20  # Warn if single stock > 20% of portfolio
