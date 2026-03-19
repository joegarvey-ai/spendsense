"""Application settings — copy to settings.py and fill in your values."""

import os
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

# Paths
PROJECT_ROOT = Path(__file__).parent.parent
DB_PATH = PROJECT_ROOT / "data" / "finance.db"
EXCEL_PATH = Path.home() / "Desktop" / "SpendSense_Dashboard.xlsx"
CSV_IMPORT_DIR = PROJECT_ROOT / "data" / "csv_imports"
LOG_DIR = PROJECT_ROOT / "logs"

# SimpleFIN (loaded from .env)
SIMPLEFIN_USERNAME = os.getenv("SIMPLEFIN_USERNAME")
SIMPLEFIN_PASSWORD = os.getenv("SIMPLEFIN_PASSWORD")
SIMPLEFIN_BASE_URL = os.getenv(
    "SIMPLEFIN_BASE_URL", "https://beta-bridge.simplefin.org/simplefin"
)

# Sync settings
DEFAULT_SYNC_DAYS = 30
MAX_SYNC_DAYS = 90  # SimpleFIN recommended limit

# Account mapping: SimpleFIN account ID → friendly name + type
# Run `python -m src.cli status` after first sync to discover your account IDs,
# then populate this map with your own accounts.
ACCOUNT_MAP = {
    # Credit Cards
    # "ACT-xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx": {"name": "Rewards Card (1234)", "type": "credit_card"},
    # "ACT-xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx": {"name": "Travel Card (5678)", "type": "credit_card"},
    # Checking
    # "ACT-xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx": {"name": "Primary Checking (9012)", "type": "checking"},
    # Savings
    # "ACT-xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx": {"name": "High-Yield Savings (3456)", "type": "savings"},
    # Loans
    # "ACT-xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx": {"name": "Auto Loan (7890)", "type": "loan"},
    # "ACT-xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx": {"name": "Home Loan (2345)", "type": "mortgage"},
    # Investment
    # "ACT-xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx": {"name": "Brokerage Individual (6789)", "type": "investment"},
    # "ACT-xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx": {"name": "Traditional IRA (0123)", "type": "investment"},
}

# Email (Phase 3)
GMAIL_SENDER = os.getenv("GMAIL_SENDER")
GMAIL_APP_PASSWORD = os.getenv("GMAIL_APP_PASSWORD")
EMAIL_PRIMARY = os.getenv("EMAIL_PRIMARY")      # Full digest recipient
EMAIL_SECONDARY = os.getenv("EMAIL_SECONDARY")  # Summary digest recipient

# Alert thresholds (configurable)
ALERT_THRESHOLDS = {
    "large_transaction": 500,
    "category_spike_pct": 1.3,
    "new_vendor_min_amount": 50,
    "budget_pace_warning_pct": 0.9,
    "unusual_day_multiplier": 2.0,
}
