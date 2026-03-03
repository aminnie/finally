"""FastAPI entrypoint for FinAlly."""

from __future__ import annotations

import asyncio
import logging
import os
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from app.db import (
    add_chat_message,
    add_watchlist_ticker,
    execute_trade,
    get_portfolio_history,
    get_portfolio_summary,
    get_recent_chat_messages,
    get_watchlist,
    initialize_database,
    record_portfolio_snapshot,
    remove_watchlist_ticker,
)
from app.llm import generate_chat_response
from app.market import PriceCache, create_market_data_source, create_stream_router
from app.schemas import ChatRequest, TradeRequest, WatchlistAddRequest

logger = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO)


class RuntimeState:
    def __init__(self) -> None:
        self.price_cache = PriceCache()
        self.market_source = None
        self.snapshot_task: asyncio.Task | None = None


state = RuntimeState()


def load_env() -> None:
    env_path = Path(__file__).resolve().parents[2] / ".env"

    try:
        from dotenv import load_dotenv
    except Exception:
        if not env_path.exists():
            return
        for raw_line in env_path.read_text().splitlines():
            line = raw_line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, value = line.split("=", 1)
            key = key.strip()
            value = value.strip().strip('"').strip("'")
            if key and key not in os.environ:
                os.environ[key] = value
        return

    load_dotenv(env_path, override=False)


def market_source():
    if state.market_source is None:
        raise HTTPException(status_code=503, detail="Market source not initialized.")
    return state.market_source


async def snapshot_loop() -> None:
    while True:
        try:
            summary = get_portfolio_summary(state.price_cache)
            record_portfolio_snapshot(summary["total_value"])
        except Exception:
            logger.exception("Failed recording periodic portfolio snapshot")
        await asyncio.sleep(30)


@asynccontextmanager
async def lifespan(app: FastAPI):
    load_env()
    initialize_database()

    state.market_source = create_market_data_source(state.price_cache)
    watchlist = get_watchlist()
    await state.market_source.start(watchlist)

    summary = get_portfolio_summary(state.price_cache)
    record_portfolio_snapshot(summary["total_value"])
    state.snapshot_task = asyncio.create_task(snapshot_loop(), name="portfolio-snapshots")
    try:
        yield
    finally:
        if state.snapshot_task and not state.snapshot_task.done():
            state.snapshot_task.cancel()
            try:
                await state.snapshot_task
            except asyncio.CancelledError:
                pass
        if state.market_source is not None:
            await state.market_source.stop()


app = FastAPI(title="FinAlly", version="0.1.0", lifespan=lifespan)

# For local dev convenience; deployment is same-origin.
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(create_stream_router(state.price_cache))


@app.get("/api/health")
async def health() -> dict:
    return {"status": "ok"}


@app.get("/api/watchlist")
async def watchlist() -> dict:
    tickers = get_watchlist()
    rows = []
    for ticker in tickers:
        update = state.price_cache.get(ticker)
        rows.append(
            {
                "ticker": ticker,
                "price": update.price if update else None,
                "previous_price": update.previous_price if update else None,
                "change_percent": update.change_percent if update else None,
                "timestamp": update.timestamp if update else None,
            }
        )
    return {"tickers": rows}


@app.post("/api/watchlist")
async def add_watchlist(payload: WatchlistAddRequest) -> dict:
    ticker = payload.ticker.upper().strip()
    created = add_watchlist_ticker(ticker)
    if created:
        await market_source().add_ticker(ticker)
    return {"ticker": ticker, "added": created}


@app.delete("/api/watchlist/{ticker}")
async def delete_watchlist(ticker: str) -> dict:
    symbol = ticker.upper().strip()
    removed = remove_watchlist_ticker(symbol)
    if removed:
        await market_source().remove_ticker(symbol)
    return {"ticker": symbol, "removed": removed}


@app.get("/api/portfolio")
async def portfolio() -> dict:
    return get_portfolio_summary(state.price_cache)


@app.get("/api/portfolio/history")
async def portfolio_history() -> dict:
    return {"history": get_portfolio_history()}


@app.post("/api/portfolio/trade")
async def trade(payload: TradeRequest) -> dict:
    ticker = payload.ticker.upper().strip()
    price = state.price_cache.get_price(ticker)
    if price is None:
        raise HTTPException(status_code=400, detail=f"Ticker {ticker} has no live price.")

    try:
        executed = execute_trade(
            ticker=ticker, side=payload.side, quantity=payload.quantity, price=price
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    summary = get_portfolio_summary(state.price_cache)
    record_portfolio_snapshot(summary["total_value"])

    return {
        "trade": {
            "ticker": executed.ticker,
            "side": executed.side,
            "quantity": executed.quantity,
            "price": executed.price,
            "notional": executed.notional,
        },
        "portfolio": summary,
    }


@app.post("/api/chat")
async def chat(payload: ChatRequest) -> dict:
    user_message = payload.message.strip()
    add_chat_message(role="user", content=user_message)

    portfolio_context = get_portfolio_summary(state.price_cache)
    recent = get_recent_chat_messages(limit=20)

    llm = generate_chat_response(
        user_message=user_message,
        portfolio_context=portfolio_context,
        recent_messages=recent,
    )

    executed_trades: list[dict] = []
    watchlist_updates: list[dict] = []
    errors: list[str] = []

    for trade_action in llm.trades:
        ticker = trade_action.ticker.upper().strip()
        live_price = state.price_cache.get_price(ticker)
        if live_price is None:
            errors.append(f"No live price for {ticker}; trade skipped.")
            continue

        try:
            executed = execute_trade(
                ticker=ticker,
                side=trade_action.side,
                quantity=trade_action.quantity,
                price=live_price,
            )
            executed_trades.append(
                {
                    "ticker": executed.ticker,
                    "side": executed.side,
                    "quantity": executed.quantity,
                    "price": executed.price,
                    "notional": executed.notional,
                }
            )
        except ValueError as exc:
            errors.append(f"Trade {trade_action.side} {trade_action.quantity} {ticker}: {exc}")

    for change in llm.watchlist_changes:
        ticker = change.ticker.upper().strip()
        action = change.action.lower().strip()

        if action == "add":
            added = add_watchlist_ticker(ticker)
            if added:
                await market_source().add_ticker(ticker)
            watchlist_updates.append({"ticker": ticker, "action": "add", "applied": added})
        elif action == "remove":
            removed = remove_watchlist_ticker(ticker)
            if removed:
                await market_source().remove_ticker(ticker)
            watchlist_updates.append({"ticker": ticker, "action": "remove", "applied": removed})
        else:
            errors.append(f"Unknown watchlist action '{action}' for {ticker}")

    summary = get_portfolio_summary(state.price_cache)
    record_portfolio_snapshot(summary["total_value"])

    actions = {
        "trades": executed_trades,
        "watchlist_changes": watchlist_updates,
        "errors": errors,
    }
    add_chat_message(role="assistant", content=llm.message, actions=actions)

    return {
        "message": llm.message,
        "trades": executed_trades,
        "watchlist_changes": watchlist_updates,
        "errors": errors,
        "portfolio": summary,
    }


# Static frontend serving
frontend_dir = Path(__file__).resolve().parents[2] / "frontend" / "out"
assets_dir = frontend_dir / "assets"
if assets_dir.exists():
    app.mount("/assets", StaticFiles(directory=assets_dir), name="assets")
next_dir = frontend_dir / "_next"
if next_dir.exists():
    app.mount("/_next", StaticFiles(directory=next_dir), name="next")


@app.get("/{path:path}")
async def spa(path: str):
    requested = (frontend_dir / path).resolve()
    if path and requested.exists() and requested.is_file() and frontend_dir in requested.parents:
        return FileResponse(requested)
    index = frontend_dir / "index.html"
    if index.exists():
        return FileResponse(index)
    raise HTTPException(status_code=404, detail="Frontend build not found.")
