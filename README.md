# SpendSense

An integrated personal finance intelligence layer built with Python. Connects to bank accounts via SimpleFIN Bridge, categorizes transactions with regex rules, generates an Excel dashboard with SUMIFS formulas, sends weekly email digests, and tracks investment portfolios with market data from Yahoo Finance.

Gives individuals and families control over spending, saving, and investment decisions — with real-time insight, not guesswork.

## Architecture

```
SimpleFIN Bridge API ──→ SQLite DB ──→ Excel Dashboard (SUMIFS)
                              │
                              ├──→ Alert Engine (6 alert types)
                              ├──→ Weekly Email Digest (Gmail SMTP)
                              ├──→ Portfolio Analyzer (yfinance)
                              └──→ Strategy Advisor (debt vs invest optimizer)
```

## Features

### Phase 1-2: Transaction Pipeline & Excel Dashboard
- **SimpleFIN Bridge integration** — pulls transactions from all linked bank accounts (checking, savings, credit cards, loans, investments)
- **Regex-based categorizer** — 80+ rules with tier1/tier2 taxonomy (Essential, Non-Essential, Discretionary, Fixed, Transfer, Income, Allocation). **Categories are generalized examples using common national merchants — you must customize `config/categories.py` for your own financial institutions and local merchants after your first sync.**
- **Double-counting safeguards** — deduplicates credit card payments, internal transfers, and loan payments that appear on both sides
- **Excel dashboard** — all data cells are SUMIFS formulas referencing a Transaction Log sheet. Edit categories in the Transaction Log and the Dashboard updates instantly
- **Override system** — manual category corrections persist across re-syncs via SQLite + Excel Override column

### Phase 3: Alerts & Weekly Digest
- **6 alert types**: large transaction, category spike, new vendor, over-budget pace, unusual spending day, missing category
- **Monday Money Brief** — HTML email digest with week-over-week comparison, MTD tracking, projected surplus/deficit, and verdict (ON TRACK / WATCH IT / OVER BUDGET)
- **Dual-recipient system** — full digest for the primary user, summary version for a partner
- **Gmail App Password** authentication (no OAuth complexity)
- **macOS launchd scheduling** — daily sync at 6 AM, weekly digest on Monday at 7 AM

### Phase 4: Investment Analysis & Strategy
- **Brokerage PDF/CSV importer** — extracts holdings with share counts from monthly statements or CSV exports (tested with common brokerage formats)
- **yfinance market data** — live prices, sector classification, dividend yields, P/E ratios, beta, 52-week ranges
- **Portfolio analyzer** — total return, sector allocation, concentration risk alerts (>20% single stock), performance vs S&P 500
- **Dividend income estimator** — annual yield projection from current holdings
- **Strategy advisor** — priority ladder optimizer for surplus allocation:
  1. IRA max ($7K limit) — tax-advantaged
  2. High-interest debt payoff — guaranteed return
  3. Taxable investing — expected market return
  4. Extra mortgage principal — lowest guaranteed return
- **Debt freedom projections** — months to payoff with and without extra payments
- **IRA contribution tracker** — YTD progress bar with monthly target to max by December

## Project Structure

```
spendsense/
├── .env.example                          # Template for credentials
├── .gitignore
├── requirements.txt
├── config/
│   ├── settings.example.py               # App config — copy to settings.py
│   ├── portfolio_config.example.py       # Debt/investment params — copy to portfolio_config.py
│   ├── categories.py                     # 80+ regex categorization rules
│   └── accounts.py                       # Account type/name helpers
├── src/
│   ├── cli.py                            # Click CLI with 15+ commands
│   ├── sync.py                           # Orchestrator: pull → categorize → store → Excel
│   ├── simplefin_client.py               # SimpleFIN Bridge API client
│   ├── categorize.py                     # Regex rule engine with amount-based overrides
│   ├── db.py                             # SQLite schema + CRUD
│   ├── excel_writer.py                   # SUMIFS formula generator + Transaction Log writer
│   ├── alerts.py                         # 6-type alert detection engine
│   ├── email_digest.py                   # Weekly digest generator (Jinja2)
│   ├── email_sender.py                   # Gmail SMTP with App Password
│   ├── brokerage_import.py               # PDF/CSV parser + dividend fallback
│   ├── market_data.py                    # yfinance wrapper with SQLite caching
│   ├── portfolio_analyzer.py             # Performance, allocation, benchmarks
│   └── strategy_advisor.py               # Debt vs invest optimizer
├── templates/
│   ├── digest_primary.html               # Full digest email template
│   └── digest_summary.html              # Summary digest for partner
├── scripts/
│   ├── setup_simplefin.py                # SimpleFIN token claim utility
│   └── install_launchd.py                # macOS scheduler installer
├── launchd/
│   ├── com.spendsense.sync.plist         # Daily sync schedule
│   └── com.spendsense.digest.plist       # Weekly digest schedule
└── data/                                 # (gitignored) SQLite DB + exports
```

## Setup

### Prerequisites
- Python 3.9+
- macOS (for launchd scheduling) or any Unix for manual runs
- SimpleFIN Bridge account ($1.50/mo or $15/yr)
- Gmail account with App Password enabled

### Installation

```bash
git clone https://github.com/joegarvey-ai/spendsense.git
cd spendsense

# Install dependencies
pip install -r requirements.txt

# Configure
cp .env.example .env                              # Fill in credentials
cp config/settings.example.py config/settings.py  # Add your account IDs
cp config/portfolio_config.example.py config/portfolio_config.py  # Add your debt params

# Initialize database
python -m src.cli sync

# (Optional) Set up daily automation on macOS
python scripts/install_launchd.py
```

### SimpleFIN Setup
1. Sign up at [SimpleFIN Bridge](https://beta-bridge.simplefin.org)
2. Link your bank accounts
3. Go to **Apps** → create a Setup Token
4. Run `python scripts/setup_simplefin.py` and paste the token
5. Run `python -m src.cli sync` — your first transactions will appear

### Gmail Setup
1. Enable 2FA on your Google account
2. Go to [App Passwords](https://myaccount.google.com/apppasswords)
3. Generate a password for "Mail"
4. Add to `.env` as `GMAIL_APP_PASSWORD`

## CLI Reference

```bash
# Transaction sync
python -m src.cli sync                    # Sync last 30 days
python -m src.cli sync --days 75          # Backfill (max ~90)
python -m src.cli recategorize            # Re-run rules on all transactions

# Category management
python -m src.cli uncategorized           # Show uncategorized transactions
python -m src.cli override --txn-id ID --tier1 X --tier2 Y

# Digest & alerts
python -m src.cli digest --preview        # Preview without sending
python -m src.cli digest                  # Send to both recipients
python -m src.cli alerts                  # Run alert engine

# Portfolio
python -m src.cli portfolio refresh       # Fetch live prices
python -m src.cli portfolio summary       # Holdings table
python -m src.cli portfolio allocation    # Sector breakdown
python -m src.cli portfolio ira           # IRA contribution progress
python -m src.cli portfolio report        # Full report with strategy
python -m src.cli strategy --extra 2000   # Optimizer for $2K/mo surplus
```

## Tech Stack

- **Python 3.9** — no framework, just stdlib + focused libraries
- **SQLite** — single-file database, no server needed
- **openpyxl** — Excel read/write with SUMIFS formula generation
- **yfinance** — Yahoo Finance market data
- **Jinja2** — HTML email templating
- **Click** — CLI framework
- **SimpleFIN Bridge** — bank account aggregation API

## Design Decisions

- **Excel as the reporting layer** — SUMIFS formulas reference the Transaction Log sheet directly. Edit a category in the Transaction Log and the Dashboard recalculates instantly. No code deployment needed for corrections.
- **Regex over ML for categorization** — deterministic, auditable, and fast. 80+ rules cover 95%+ of transactions. Manual overrides handle the rest.
- **Gmail App Password over OAuth2** — simpler setup for a personal tool. No token refresh complexity.
- **PDF/CSV parsing over brokerage APIs** — avoids storing brokerage login credentials. Works with monthly statement exports from common brokerages.
- **Strategy advisor shows math, not advice** — presents both the "math-optimal" and "sleep-well" allocation. The user makes the final call.

## License

MIT
