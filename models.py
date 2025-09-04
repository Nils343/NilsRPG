"""Data models used by the NilsRPG application."""

from pydantic import BaseModel


class IdentitiesResponse(BaseModel):
    identities: list[str]


class InventoryItem(BaseModel):
    name: str
    description: str
    weight: float
    equipped: bool


class PerkSkill(BaseModel):
    name: str
    degree: str
    description: str


class Attributes(BaseModel):
    Name: str
    Background: str
    Age: str
    Health: str
    Sanity: str
    Hunger: str
    Thirst: str
    Stamina: str


class Environment(BaseModel):
    Location: str
    Daytime: str
    Light: str
    Temperature: str
    Humidity: str
    Wind: str
    Soundscape: str


class GameResponse(BaseModel):
    day: int
    time: str
    current_situation: str
    environment: Environment
    inventory: list[InventoryItem]
    perks_skills: list[PerkSkill]
    attributes: Attributes
    options: list[str]
    image_prompt: str
