from __future__ import annotations

"""Application configuration handling."""

from dataclasses import dataclass, asdict
import json
from pathlib import Path


@dataclass
class AppConfig:
    """User adjustable settings for the application."""

    model: str = "gpt-4o-mini"
    enable_audio: bool = True
    enable_images: bool = True


def load_config(path: str | Path) -> AppConfig:
    """Load configuration from *path*.

    Returns a default :class:`AppConfig` if the file is missing.
    """

    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        return AppConfig(**data)
    except FileNotFoundError:
        return AppConfig()


def save_config(cfg: AppConfig, path: str | Path) -> None:
    """Persist *cfg* to *path* as JSON."""

    with open(path, "w", encoding="utf-8") as f:
        json.dump(asdict(cfg), f, indent=2)
