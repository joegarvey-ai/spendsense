from __future__ import annotations

# The account map comes from settings.py (user-configured).
# ACCOUNT_MAP must be defined in settings.py with your SimpleFIN account IDs.
# See settings.example.py for the format.
from config.loader import settings


def get_friendly_name(account_id: str) -> str | None:
    """Return the friendly name for a SimpleFIN account ID, or None if unmapped."""
    entry = settings.ACCOUNT_MAP.get(account_id)
    return entry["name"] if entry else None


def get_account_type(account_id: str) -> str | None:
    """Return the account type for a SimpleFIN account ID, or None if unmapped."""
    entry = settings.ACCOUNT_MAP.get(account_id)
    return entry["type"] if entry else None
