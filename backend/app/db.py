"""SQLite persistence and portfolio business logic."""

from __future__ import annotations

import json
import os
import sqlite3
import uuid
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from app.market import PriceCache

DEFAULT_USER_ID = "default"
DEFAULT_CASH_BALANCE = 10_000.0
DEFAULT_WATCHLIST = [
    "AAPL",
    "GOOGL",
    "MSFT",
    "AMZN",
    "TSLA",
    "NVDA",
    "META",
    "JPM",
    "V",
    "NFLX",
]


@dataclass(slots=True)
class TradeExecution:
    ticker: str
    side: str
    quantity: float
    price: float
    notional: float


def utc_now_iso() -> str:
    return datetime.now(UTC).isoformat()


def app_root() -> Path:
    # backend/app/db.py -> repo root is 2 parents up from backend/
    return Path(__file__).resolve().parents[2]


def db_path() -> Path:
    configured = os.getenv("FINALLY_DB_PATH", "").strip()
    if configured:
        return Path(configured).expanduser().resolve()
    return app_root() / "db" / "finally.db"


@contextmanager
def get_connection() -> sqlite3.Connection:
    path = db_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    try:
        yield conn
    finally:
        conn.close()


def initialize_database() -> None:
    with get_connection() as conn:
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS users_profile (
                id TEXT PRIMARY KEY,
                cash_balance REAL NOT NULL DEFAULT 10000.0,
                created_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS watchlist (
                id TEXT PRIMARY KEY,
                user_id TEXT NOT NULL,
                ticker TEXT NOT NULL,
                added_at TEXT NOT NULL,
                UNIQUE(user_id, ticker)
            );

            CREATE TABLE IF NOT EXISTS positions (
                id TEXT PRIMARY KEY,
                user_id TEXT NOT NULL,
                ticker TEXT NOT NULL,
                quantity REAL NOT NULL,
                avg_cost REAL NOT NULL,
                updated_at TEXT NOT NULL,
                UNIQUE(user_id, ticker)
            );

            CREATE TABLE IF NOT EXISTS trades (
                id TEXT PRIMARY KEY,
                user_id TEXT NOT NULL,
                ticker TEXT NOT NULL,
                side TEXT NOT NULL,
                quantity REAL NOT NULL,
                price REAL NOT NULL,
                executed_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS portfolio_snapshots (
                id TEXT PRIMARY KEY,
                user_id TEXT NOT NULL,
                total_value REAL NOT NULL,
                recorded_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS chat_messages (
                id TEXT PRIMARY KEY,
                user_id TEXT NOT NULL,
                role TEXT NOT NULL,
                content TEXT NOT NULL,
                actions TEXT,
                created_at TEXT NOT NULL
            );
            """
        )

        now = utc_now_iso()
        conn.execute(
            "INSERT OR IGNORE INTO users_profile (id, cash_balance, created_at) VALUES (?, ?, ?)",
            (DEFAULT_USER_ID, DEFAULT_CASH_BALANCE, now),
        )
        for ticker in DEFAULT_WATCHLIST:
            conn.execute(
                """
                INSERT OR IGNORE INTO watchlist (id, user_id, ticker, added_at)
                VALUES (?, ?, ?, ?)
                """,
                (str(uuid.uuid4()), DEFAULT_USER_ID, ticker, now),
            )
        conn.commit()


def get_watchlist() -> list[str]:
    with get_connection() as conn:
        rows = conn.execute(
            "SELECT ticker FROM watchlist WHERE user_id = ? ORDER BY ticker",
            (DEFAULT_USER_ID,),
        ).fetchall()
    return [str(row["ticker"]) for row in rows]


def add_watchlist_ticker(ticker: str) -> bool:
    ticker = ticker.upper().strip()
    if not ticker:
        return False

    with get_connection() as conn:
        cursor = conn.execute(
            """
            INSERT OR IGNORE INTO watchlist (id, user_id, ticker, added_at)
            VALUES (?, ?, ?, ?)
            """,
            (str(uuid.uuid4()), DEFAULT_USER_ID, ticker, utc_now_iso()),
        )
        conn.commit()
        return cursor.rowcount > 0


def remove_watchlist_ticker(ticker: str) -> bool:
    ticker = ticker.upper().strip()
    with get_connection() as conn:
        cursor = conn.execute(
            "DELETE FROM watchlist WHERE user_id = ? AND ticker = ?",
            (DEFAULT_USER_ID, ticker),
        )
        conn.commit()
        return cursor.rowcount > 0


def get_cash_balance() -> float:
    with get_connection() as conn:
        row = conn.execute(
            "SELECT cash_balance FROM users_profile WHERE id = ?",
            (DEFAULT_USER_ID,),
        ).fetchone()
    if row is None:
        return DEFAULT_CASH_BALANCE
    return float(row["cash_balance"])


def get_positions() -> list[dict]:
    with get_connection() as conn:
        rows = conn.execute(
            """
            SELECT ticker, quantity, avg_cost, updated_at
            FROM positions
            WHERE user_id = ?
            ORDER BY ticker
            """,
            (DEFAULT_USER_ID,),
        ).fetchall()
    return [
        {
            "ticker": str(row["ticker"]),
            "quantity": float(row["quantity"]),
            "avg_cost": float(row["avg_cost"]),
            "updated_at": str(row["updated_at"]),
        }
        for row in rows
    ]


def execute_trade(ticker: str, side: str, quantity: float, price: float) -> TradeExecution:
    ticker = ticker.upper().strip()
    side = side.lower().strip()
    quantity = float(quantity)
    price = float(price)

    if side not in {"buy", "sell"}:
        raise ValueError("Trade side must be 'buy' or 'sell'.")
    if quantity <= 0:
        raise ValueError("Quantity must be greater than 0.")
    if price <= 0:
        raise ValueError("Price unavailable for ticker.")

    now = utc_now_iso()
    notional = round(quantity * price, 2)

    with get_connection() as conn:
        cash_row = conn.execute(
            "SELECT cash_balance FROM users_profile WHERE id = ?",
            (DEFAULT_USER_ID,),
        ).fetchone()
        if cash_row is None:
            raise ValueError("User profile not found.")

        cash_balance = float(cash_row["cash_balance"])

        pos_row = conn.execute(
            """
            SELECT id, quantity, avg_cost FROM positions
            WHERE user_id = ? AND ticker = ?
            """,
            (DEFAULT_USER_ID, ticker),
        ).fetchone()

        if side == "buy":
            if cash_balance < notional:
                raise ValueError("Insufficient cash balance.")

            new_cash = round(cash_balance - notional, 2)

            if pos_row is None:
                conn.execute(
                    """
                    INSERT INTO positions (id, user_id, ticker, quantity, avg_cost, updated_at)
                    VALUES (?, ?, ?, ?, ?, ?)
                    """,
                    (str(uuid.uuid4()), DEFAULT_USER_ID, ticker, quantity, price, now),
                )
            else:
                existing_qty = float(pos_row["quantity"])
                existing_avg = float(pos_row["avg_cost"])
                total_qty = existing_qty + quantity
                new_avg = ((existing_qty * existing_avg) + (quantity * price)) / total_qty
                conn.execute(
                    """
                    UPDATE positions
                    SET quantity = ?, avg_cost = ?, updated_at = ?
                    WHERE id = ?
                    """,
                    (total_qty, round(new_avg, 4), now, str(pos_row["id"])),
                )

            conn.execute(
                "UPDATE users_profile SET cash_balance = ? WHERE id = ?",
                (new_cash, DEFAULT_USER_ID),
            )

        if side == "sell":
            if pos_row is None:
                raise ValueError("No position found for ticker.")

            existing_qty = float(pos_row["quantity"])
            if quantity > existing_qty:
                raise ValueError("Insufficient shares to sell.")

            new_qty = round(existing_qty - quantity, 8)
            new_cash = round(cash_balance + notional, 2)

            if new_qty <= 0:
                conn.execute("DELETE FROM positions WHERE id = ?", (str(pos_row["id"]),))
            else:
                conn.execute(
                    "UPDATE positions SET quantity = ?, updated_at = ? WHERE id = ?",
                    (new_qty, now, str(pos_row["id"])),
                )

            conn.execute(
                "UPDATE users_profile SET cash_balance = ? WHERE id = ?",
                (new_cash, DEFAULT_USER_ID),
            )

        conn.execute(
            """
            INSERT INTO trades (id, user_id, ticker, side, quantity, price, executed_at)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (str(uuid.uuid4()), DEFAULT_USER_ID, ticker, side, quantity, price, now),
        )
        conn.commit()

    return TradeExecution(
        ticker=ticker,
        side=side,
        quantity=quantity,
        price=round(price, 2),
        notional=notional,
    )


def get_portfolio_summary(price_cache: PriceCache) -> dict:
    cash = get_cash_balance()
    positions = get_positions()

    enriched_positions: list[dict] = []
    market_value = 0.0
    total_cost = 0.0

    for pos in positions:
        ticker = pos["ticker"]
        qty = pos["quantity"]
        avg_cost = pos["avg_cost"]

        current_price = price_cache.get_price(ticker)
        if current_price is None:
            current_price = avg_cost

        value = qty * current_price
        cost_basis = qty * avg_cost
        pnl = value - cost_basis
        pnl_percent = (pnl / cost_basis * 100) if cost_basis > 0 else 0.0

        market_value += value
        total_cost += cost_basis

        enriched_positions.append(
            {
                **pos,
                "current_price": round(current_price, 2),
                "market_value": round(value, 2),
                "unrealized_pnl": round(pnl, 2),
                "pnl_percent": round(pnl_percent, 4),
            }
        )

    total_value = cash + market_value
    unrealized_pnl_total = market_value - total_cost
    return {
        "cash_balance": round(cash, 2),
        "positions": enriched_positions,
        "market_value": round(market_value, 2),
        "total_value": round(total_value, 2),
        "unrealized_pnl": round(unrealized_pnl_total, 2),
    }


def record_portfolio_snapshot(total_value: float) -> None:
    with get_connection() as conn:
        conn.execute(
            """
            INSERT INTO portfolio_snapshots (id, user_id, total_value, recorded_at)
            VALUES (?, ?, ?, ?)
            """,
            (str(uuid.uuid4()), DEFAULT_USER_ID, float(total_value), utc_now_iso()),
        )
        conn.commit()


def get_portfolio_history(limit: int = 500) -> list[dict]:
    with get_connection() as conn:
        rows = conn.execute(
            """
            SELECT total_value, recorded_at
            FROM portfolio_snapshots
            WHERE user_id = ?
            ORDER BY recorded_at DESC
            LIMIT ?
            """,
            (DEFAULT_USER_ID, int(limit)),
        ).fetchall()

    history = [
        {
            "total_value": float(row["total_value"]),
            "recorded_at": str(row["recorded_at"]),
        }
        for row in rows
    ]
    history.reverse()
    return history


def add_chat_message(role: str, content: str, actions: dict | None = None) -> None:
    with get_connection() as conn:
        conn.execute(
            """
            INSERT INTO chat_messages (id, user_id, role, content, actions, created_at)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                str(uuid.uuid4()),
                DEFAULT_USER_ID,
                role,
                content,
                json.dumps(actions) if actions else None,
                utc_now_iso(),
            ),
        )
        conn.commit()


def get_recent_chat_messages(limit: int = 20) -> list[dict]:
    with get_connection() as conn:
        rows = conn.execute(
            """
            SELECT role, content, actions, created_at
            FROM chat_messages
            WHERE user_id = ?
            ORDER BY created_at DESC
            LIMIT ?
            """,
            (DEFAULT_USER_ID, int(limit)),
        ).fetchall()

    out = []
    for row in reversed(rows):
        actions = row["actions"]
        out.append(
            {
                "role": str(row["role"]),
                "content": str(row["content"]),
                "actions": json.loads(actions) if actions else None,
                "created_at": str(row["created_at"]),
            }
        )
    return out
