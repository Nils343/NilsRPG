"""Game save/load helpers."""

from __future__ import annotations

import base64
import json
import pickle
from dataclasses import asdict
from pathlib import Path
from typing import Any

from state import GameState

SAVE_VERSION = 1


def save_state(path: str | Path, state: GameState, thumbnail: bytes | None = None) -> None:
    """Write *state* to *path* as versioned JSON."""

    data: dict[str, Any] = {
        "version": SAVE_VERSION,
        "state": asdict(state),
        "thumbnail": base64.b64encode(thumbnail).decode("ascii") if thumbnail else None,
    }
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)


def load_state(path: str | Path) -> GameState:
    """Load game state from *path* supporting legacy pickle files."""

    path = str(path)
    if path.endswith(".dat"):
        with open(path, "rb") as f:
            old = pickle.load(f)
        state_dict = old.get("state", old)
        return GameState(**state_dict)

    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)
    return GameState(**data["state"])
