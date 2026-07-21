"""Lazy configuration loader.

Provides `settings` and `portfolio_config` objects that defer import until
first attribute access. This allows the test suite and CLI help to run
without requiring the user to create config files first.
"""
from __future__ import annotations

import os
from pathlib import Path


class _LazySettings:
    """Proxy that imports config.settings on first attribute access."""

    _module = None
    _DEFAULTS = {
        "DB_PATH": Path(__file__).parent.parent / "data" / "finance.db",
        "EXCEL_PATH": Path.home() / "Desktop" / "SpendSense_Dashboard.xlsx",
        "CSV_IMPORT_DIR": Path(__file__).parent.parent / "data" / "csv_imports",
        "LOG_DIR": Path(__file__).parent.parent / "logs",
        "DEFAULT_SYNC_DAYS": 30,
        "MAX_SYNC_DAYS": 90,
        "ACCOUNT_MAP": {},
        "ALERT_THRESHOLDS": {
            "large_transaction": 500,
            "category_spike_pct": 1.3,
            "new_vendor_min_amount": 50,
            "budget_pace_warning_pct": 0.9,
            "unusual_day_multiplier": 2.0,
        },
    }
    # Env-var-backed attributes are resolved at access time so tests can
    # patch os.environ and .env loading order doesn't matter.
    _ENV_DEFAULTS = {
        "SIMPLEFIN_USERNAME": ("SIMPLEFIN_USERNAME", None),
        "SIMPLEFIN_PASSWORD": ("SIMPLEFIN_PASSWORD", None),
        "SIMPLEFIN_BASE_URL": ("SIMPLEFIN_BASE_URL", "https://beta-bridge.simplefin.org/simplefin"),
        "GMAIL_SENDER": ("GMAIL_SENDER", None),
        "GMAIL_APP_PASSWORD": ("GMAIL_APP_PASSWORD", None),
        "EMAIL_PRIMARY": ("EMAIL_PRIMARY", None),
        "EMAIL_SECONDARY": ("EMAIL_SECONDARY", None),
    }

    def _load(self):
        if self._module is not None:
            return
        try:
            import config.settings as mod
            type(self)._module = mod
        except ImportError:
            type(self)._module = False  # Sentinel: tried and failed

    def __getattr__(self, name):
        if name.startswith("_"):
            raise AttributeError(name)
        self._load()
        if self._module:
            return getattr(self._module, name)
        if name in self._ENV_DEFAULTS:
            env_key, fallback = self._ENV_DEFAULTS[name]
            return os.getenv(env_key, fallback)
        if name in self._DEFAULTS:
            return self._DEFAULTS[name]
        raise AttributeError(
            f"Settings attribute '{name}' not found. "
            f"Copy config/settings.example.py to config/settings.py and fill in your values."
        )


class _LazyPortfolioConfig:
    """Proxy that imports config.portfolio_config on first attribute access."""

    _module = None
    _DEFAULTS = {
        "MORTGAGE_RATE": 0.04,
        "MORTGAGE_BALANCE": 0,
        "MORTGAGE_MONTHLY": 0,
        "MORTGAGE_TERM_REMAINING": 0,
        "CAR_LOAN_RATE": 0.055,
        "CAR_BALANCE": 0,
        "CAR_MONTHLY": 0,
        "CAR_TERM_REMAINING": 0,
        "IRA_ANNUAL_LIMIT": 7000,
        "IRA_ACCOUNT": "Traditional IRA",
        "ASSUMED_MARKET_RETURN": 0.10,
        "RISK_FREE_RATE": 0.043,
        "BENCHMARKS": {"S&P 500": "^GSPC"},
        "BROKERAGE_ACCOUNTS": {},
        "KNOWN_TICKERS": [],
        "CONCENTRATION_WARN_PCT": 0.20,
    }

    def _load(self):
        if self._module is not None:
            return
        try:
            import config.portfolio_config as mod
            type(self)._module = mod
        except ImportError:
            type(self)._module = False

    def __getattr__(self, name):
        if name.startswith("_"):
            raise AttributeError(name)
        self._load()
        if self._module:
            return getattr(self._module, name)
        if name in self._DEFAULTS:
            return self._DEFAULTS[name]
        raise AttributeError(
            f"Portfolio config attribute '{name}' not found. "
            f"Copy config/portfolio_config.example.py to config/portfolio_config.py."
        )


settings = _LazySettings()
portfolio_config = _LazyPortfolioConfig()
