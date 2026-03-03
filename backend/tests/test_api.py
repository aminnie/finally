"""API route tests for core FinAlly flows."""

from __future__ import annotations

import importlib

import pytest
from fastapi.testclient import TestClient


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("FINALLY_DB_PATH", str(tmp_path / "finally.db"))
    monkeypatch.setenv("LLM_MOCK", "true")
    monkeypatch.delenv("MASSIVE_API_KEY", raising=False)

    import app.main as main_module

    importlib.reload(main_module)

    with TestClient(main_module.app) as test_client:
        yield test_client


def test_health(client: TestClient):
    response = client.get("/api/health")
    assert response.status_code == 200
    assert response.json()["status"] == "ok"


def test_default_watchlist_seeded(client: TestClient):
    response = client.get("/api/watchlist")
    assert response.status_code == 200
    data = response.json()
    assert len(data["tickers"]) == 10


def test_trade_buy_updates_portfolio(client: TestClient):
    response = client.post(
        "/api/portfolio/trade",
        json={"ticker": "AAPL", "quantity": 1, "side": "buy"},
    )
    assert response.status_code == 200

    payload = response.json()
    assert payload["trade"]["ticker"] == "AAPL"
    assert payload["trade"]["side"] == "buy"

    portfolio = payload["portfolio"]
    assert portfolio["cash_balance"] < 10000
    assert any(p["ticker"] == "AAPL" for p in portfolio["positions"])


def test_chat_mock_can_trigger_trade(client: TestClient):
    response = client.post("/api/chat", json={"message": "buy 1 MSFT"})
    assert response.status_code == 200

    payload = response.json()
    assert payload["message"].startswith("Mock mode")
    assert any(t["ticker"] == "MSFT" and t["side"] == "buy" for t in payload["trades"])
