"""Data models used by the NilsRPG application."""

from pydantic import BaseModel, ConfigDict, Field


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


class PaneSizes(BaseModel):
    """Persisted geometry for the main, left and right panes."""

    main_sash: int
    left_sashes: list[int] = Field(default_factory=list)
    right_sashes: list[int] = Field(default_factory=list)


class SaveGame(BaseModel):
    """Full representation of a saved game state."""

    model_config = ConfigDict(extra="forbid")

    save_version: int = 1

    identity: str | None = None
    style: str | None = None
    difficulty: str | None = None

    turn: int
    day: int
    time: str
    current_situation: str
    environment: Environment
    attributes: Attributes
    inventory: list[InventoryItem]
    perks_skills: list[PerkSkill]
    options: list[str]

    past_situations: list[str]
    past_options: list[str]
    past_days: list[int]
    past_times: list[str]

    previous_image_prompt: str | None = None
    character_id: str
    pane_sizes: PaneSizes | None = None
    story_text: str | None = None
    scene_image_b64: str | None = None


