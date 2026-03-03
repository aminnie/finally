"""Pydantic API schemas."""

from __future__ import annotations

from pydantic import BaseModel, Field


class TradeRequest(BaseModel):
    ticker: str = Field(min_length=1)
    quantity: float = Field(gt=0)
    side: str


class WatchlistAddRequest(BaseModel):
    ticker: str = Field(min_length=1)


class ChatRequest(BaseModel):
    message: str = Field(min_length=1)


class LLMTrade(BaseModel):
    ticker: str
    side: str
    quantity: float


class LLMWatchlistChange(BaseModel):
    ticker: str
    action: str


class LLMResponse(BaseModel):
    message: str
    trades: list[LLMTrade] = Field(default_factory=list)
    watchlist_changes: list[LLMWatchlistChange] = Field(default_factory=list)
