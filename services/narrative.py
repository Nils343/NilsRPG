"""Prompt construction and response handling."""

from __future__ import annotations

import json
from typing import Any

from models import GameResponse
from state import GameState
from .genai_client import create_client


_client = None


def _get_client():
    global _client
    if _client is None:
        _client = create_client()
    return _client


def build_prompt(state: GameState, initial: bool = False) -> str:
    """Create a text prompt from *state*."""

    if initial:
        return f"You awaken on day {state.day} at {state.time}." \
            f" You carry {', '.join(state.inventory) or 'nothing'}."
    return f"Day {state.day}, {state.time}." \
        f" Inventory: {', '.join(state.inventory) or 'empty'}"


def finalize_to_model(json_text: str) -> GameResponse:
    """Parse *json_text* into :class:`GameResponse`."""

    data: Any = json.loads(json_text)
    return GameResponse(**data)
