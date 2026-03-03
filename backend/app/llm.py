"""LLM integration with mock mode and OpenRouter via LiteLLM."""

from __future__ import annotations

import json
import os
import re
import urllib.error
import urllib.request
from typing import Any

from app.schemas import LLMResponse

MODEL = "openrouter/openai/gpt-oss-120b"
OPENROUTER_URL = "https://openrouter.ai/api/v1/chat/completions"


def _extract_mock_actions(message: str) -> tuple[list[dict], list[dict]]:
    text = message.strip()
    trades: list[dict] = []
    watchlist_changes: list[dict] = []

    buy_match = re.search(r"\bbuy\s+(\d+(?:\.\d+)?)\s+([a-zA-Z.]+)", text, re.IGNORECASE)
    sell_match = re.search(r"\bsell\s+(\d+(?:\.\d+)?)\s+([a-zA-Z.]+)", text, re.IGNORECASE)
    add_match = re.search(r"\badd\s+([a-zA-Z.]+)\s+to\s+watchlist", text, re.IGNORECASE)
    remove_match = re.search(r"\bremove\s+([a-zA-Z.]+)\s+from\s+watchlist", text, re.IGNORECASE)

    if buy_match:
        trades.append(
            {
                "ticker": buy_match.group(2).upper(),
                "side": "buy",
                "quantity": float(buy_match.group(1)),
            }
        )
    if sell_match:
        trades.append(
            {
                "ticker": sell_match.group(2).upper(),
                "side": "sell",
                "quantity": float(sell_match.group(1)),
            }
        )
    if add_match:
        watchlist_changes.append({"ticker": add_match.group(1).upper(), "action": "add"})
    if remove_match:
        watchlist_changes.append({"ticker": remove_match.group(1).upper(), "action": "remove"})

    return trades, watchlist_changes


def _mock_response(user_message: str) -> LLMResponse:
    trades, watchlist_changes = _extract_mock_actions(user_message)
    return LLMResponse(
        message="Mock mode: analyzed portfolio and prepared requested actions.",
        trades=trades,
        watchlist_changes=watchlist_changes,
    )


def _system_prompt() -> str:
    return (
        "You are FinAlly, an AI trading assistant. "
        "Be concise, data-driven, and helpful. "
        "You may suggest trades and watchlist updates. "
        "Always return strict JSON with keys: message, trades, watchlist_changes."
    )


def _build_messages(
    user_message: str, portfolio_context: dict, recent_messages: list[dict]
) -> list[dict]:
    context_blob = json.dumps(portfolio_context)
    messages: list[dict[str, Any]] = [
        {"role": "system", "content": _system_prompt()},
        {
            "role": "system",
            "content": f"Current portfolio context JSON: {context_blob}",
        },
    ]

    for message in recent_messages[-10:]:
        role = message.get("role")
        if role not in {"user", "assistant"}:
            continue
        messages.append({"role": role, "content": str(message.get("content", ""))})

    messages.append({"role": "user", "content": user_message})
    return messages


def _parse_content(content: str) -> LLMResponse:
    content = content.strip()
    if content.startswith("```"):
        content = re.sub(r"^```(?:json)?\s*", "", content)
        content = re.sub(r"\s*```$", "", content)

    data = json.loads(content)
    return LLMResponse.model_validate(data)


def generate_chat_response(
    user_message: str,
    portfolio_context: dict,
    recent_messages: list[dict],
) -> LLMResponse:
    if os.getenv("LLM_MOCK", "false").lower() == "true":
        return _mock_response(user_message)

    api_key = os.getenv("OPENROUTER_API_KEY", "").strip()
    if not api_key:
        return _mock_response(user_message)

    response_schema = {
        "type": "json_schema",
        "json_schema": {
            "name": "finally_chat_response",
            "schema": {
                "type": "object",
                "properties": {
                    "message": {"type": "string"},
                    "trades": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "properties": {
                                "ticker": {"type": "string"},
                                "side": {"type": "string", "enum": ["buy", "sell"]},
                                "quantity": {"type": "number"},
                            },
                            "required": ["ticker", "side", "quantity"],
                            "additionalProperties": False,
                        },
                    },
                    "watchlist_changes": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "properties": {
                                "ticker": {"type": "string"},
                                "action": {"type": "string", "enum": ["add", "remove"]},
                            },
                            "required": ["ticker", "action"],
                            "additionalProperties": False,
                        },
                    },
                },
                "required": ["message"],
                "additionalProperties": False,
            },
            "strict": True,
        },
    }

    body = {
        "model": MODEL,
        "messages": _build_messages(user_message, portfolio_context, recent_messages),
        "response_format": response_schema,
        "temperature": 0.2,
    }
    request = urllib.request.Request(
        OPENROUTER_URL,
        data=json.dumps(body).encode("utf-8"),
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
            "HTTP-Referer": "https://finally.local",
            "X-Title": "FinAlly",
        },
        method="POST",
    )

    try:
        with urllib.request.urlopen(request, timeout=25) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except (urllib.error.URLError, TimeoutError):
        return _mock_response(user_message)

    choices = payload.get("choices", [])
    if not choices:
        return LLMResponse(
            message="I could not generate a response.", trades=[], watchlist_changes=[]
        )
    content = choices[0].get("message", {}).get("content")
    if not content:
        return LLMResponse(
            message="I could not generate a response.", trades=[], watchlist_changes=[]
        )

    try:
        return _parse_content(content)
    except Exception:
        return LLMResponse(message=str(content), trades=[], watchlist_changes=[])
