"""Data models used by the NilsRPG application."""

from pydantic import BaseModel


class IdentitiesResponse(BaseModel):
    """Response model for identity suggestions returned by the back-end."""

    identities: list[str]


class InventoryItem(BaseModel):
    """Represents a single item held by the player."""

    name: str
    description: str
    weight: float
    equipped: bool


class PerkSkill(BaseModel):
    """Models a perk or skill with its level and description."""

    name: str
    degree: str
    description: str


class Attributes(BaseModel):
    """Character statistics reflecting physical and mental state."""

    Name: str
    Background: str
    Age: str
    Health: str
    Sanity: str
    Hunger: str
    Thirst: str
    Stamina: str


class Environment(BaseModel):
    """Environmental conditions impacting the character."""

    Location: str
    Daytime: str
    Light: str
    Temperature: str
    Humidity: str
    Wind: str
    Soundscape: str


class GameResponse(BaseModel):
    """Full response returned from the game engine for a player's action."""

    day: int
    time: str
    current_situation: str
    environment: Environment
    inventory: list[InventoryItem]
    perks_skills: list[PerkSkill]
    attributes: Attributes
    options: list[str]
    image_prompt: str

