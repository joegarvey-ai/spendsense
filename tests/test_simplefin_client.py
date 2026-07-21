"""Tests for the SimpleFIN client (using mocked responses)."""

import json
from datetime import datetime
from pathlib import Path
from unittest.mock import MagicMock, patch

from src.simplefin_client import SimpleFINClient

MOCK_RESPONSE = {
    "errors": [],
    "accounts": [
        {
            "org": {"domain": "example.org", "name": "My Credit Union"},
            "id": "ACT-001",
            "name": "Checking",
            "currency": "USD",
            "balance": "5432.10",
            "available-balance": "5432.10",
            "balance-date": 1710460800,
            "transactions": [
                {
                    "id": "TXN-001",
                    "posted": 1710374400,
                    "amount": "-52.34",
                    "description": "FRED MEYER #1234",
                    "pending": False,
                },
                {
                    "id": "TXN-002",
                    "posted": 1710374400,
                    "amount": "-6.75",
                    "description": "STARBUCKS STORE 12345",
                    "pending": True,
                },
            ],
        }
    ],
}


def test_get_all_transactions():
    client = SimpleFINClient("user", "pass", "https://example.com/simplefin")

    mock_resp = MagicMock()
    mock_resp.json.return_value = MOCK_RESPONSE
    mock_resp.raise_for_status = MagicMock()

    with patch.object(client.session, "get", return_value=mock_resp):
        txns = client.get_all_transactions(days_back=30)

    assert len(txns) == 2
    assert txns[0]["institution"] == "My Credit Union"
    assert txns[0]["id"] == "ACT-001:TXN-001"
    assert txns[0]["amount"] == "-52.34"
    assert txns[0]["pending"] is False
    assert txns[1]["pending"] is True


def test_get_accounts_metadata():
    client = SimpleFINClient("user", "pass", "https://example.com/simplefin")

    mock_resp = MagicMock()
    mock_resp.json.return_value = MOCK_RESPONSE
    mock_resp.raise_for_status = MagicMock()

    with patch.object(client.session, "get", return_value=mock_resp):
        accounts = client.get_accounts_metadata()

    assert len(accounts) == 1
    assert accounts[0]["institution"] == "My Credit Union"
    assert accounts[0]["balance"] == "5432.10"


def test_api_errors_logged():
    client = SimpleFINClient("user", "pass", "https://example.com/simplefin")

    error_response = {
        "errors": ["Institution temporarily unavailable"],
        "accounts": [],
    }
    mock_resp = MagicMock()
    mock_resp.json.return_value = error_response
    mock_resp.raise_for_status = MagicMock()

    with patch.object(client.session, "get", return_value=mock_resp):
        data = client.get_accounts()

    assert len(data["errors"]) == 1
    assert data["accounts"] == []


if __name__ == "__main__":
    import pytest
    pytest.main([__file__, "-v"])
