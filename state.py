from __future__ import annotations

"""Game state dataclasses."""

from dataclasses import dataclass, field
from typing import Dict, List


@dataclass
class GameState:
    """Represents the player's progress and world state."""

    day: int = 0
    time: str = "morning"
    attributes: Dict[str, str] = field(default_factory=dict)
    environment: Dict[str, str] = field(default_factory=dict)
    inventory: List[str] = field(default_factory=list)
    perks: List[str] = field(default_factory=list)
    history: List[str] = field(default_factory=list)
