from __future__ import annotations

# Account mapping: SimpleFIN account ID → friendly name + type
# This gets populated after first sync. Update manually after running `cli.py status`.
# CUSTOMIZE: Replace with your own SimpleFIN account IDs and friendly names.
ACCOUNT_MAP = {
    # "sfin-id-here": {"name": "Primary Checking", "type": "checking"},
    # "sfin-id-here": {"name": "Savings", "type": "savings"},
    # "sfin-id-here": {"name": "Rewards Card (1234)", "type": "credit_card"},
    # "sfin-id-here": {"name": "Travel Card (5678)", "type": "credit_card"},
}


def get_friendly_name(account_id: str) -> str | None:
    """Return the friendly name for a SimpleFIN account ID, or None if unmapped."""
    entry = ACCOUNT_MAP.get(account_id)
    return entry["name"] if entry else None


def get_account_type(account_id: str) -> str | None:
    """Return the account type for a SimpleFIN account ID, or None if unmapped."""
    entry = ACCOUNT_MAP.get(account_id)
    return entry["type"] if entry else None
